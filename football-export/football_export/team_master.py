"""
team_master.py - 球队主数据（team_id → 规范名）
====================================================
解决同一球队因翻译不同造成的名称不一致问题。

核心思路：
- 以球队 ID（homeTeam.id / awayTeam.id）为主键锚定球队身份。
- 通过 team_master_seed.json 提供"ID → 建议规范名"的受管映射（由扫描脚本生成）。
- 导出时：
  1. 有 ID 且在 seed 中 → 使用规范名；
  2. 有 ID 但不在 seed 中 → 回退当前原始名（动态新增球队），并可被记录学习；
  3. 无 ID → 直接使用原始名。

支持：
- 运行时增量学习：导出过程中发现 同一ID 的新名称变体，会记录到内存，
  供下一次"学习保存"更新 seed（可选，默认只读）。
"""

import json
import os
import threading

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SEED_PATH = os.path.join(_MODULE_DIR, "data", "team_master_seed.json")

_lock = threading.Lock()


def _load_seed(path: str) -> dict:
    """加载 seed 文件，返回 {team_id(str): {"canonical_name": str, ...}}"""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class TeamMaster:
    """球队主数据查询器（只读优先，可选增量学习）。"""

    def __init__(self, seed_path: str = None):
        self.seed_path = seed_path or DEFAULT_SEED_PATH
        self.seed = _load_seed(self.seed_path)
        # 增量学习缓存：team_id -> {name: count}（导出中发现的新变体）
        self.learned = {}
        self._learned_lock = threading.Lock()

    # ---------- 查询 ----------
    def canonical_name(self, team_id, fallback_name: str = "") -> str:
        """根据球队 ID 返回规范名；未知 ID 或无 ID 回退原始名。"""
        tid = self._norm_id(team_id)
        if tid:
            info = self.seed.get(tid)
            if info and info.get("canonical_name"):
                return info["canonical_name"]
            # seed 中没有 → 若有增量学习命中则用之，否则回退原始名
            learned = self._get_learned(tid)
            if learned:
                return learned
        return fallback_name if fallback_name else ""

    def canonical_by_variant(self, name: str) -> str:
        """
        无 ID 锚点时的兜底：按名称变体反查规范名。
        提高"有名称、无 ID"数据的归一化能力。
        """
        name = (name or "").strip()
        if not name:
            return ""
        # 先按规范名直接命中
        for tid, info in self.seed.items():
            if info.get("canonical_name") == name:
                return name
        # 再按变体命中（取出现次数最多的规范名为准）
        best = None
        best_count = -1
        for tid, info in self.seed.items():
            variants = info.get("name_variants") or {}
            if name in variants:
                if variants[name] > best_count:
                    best_count = variants[name]
                    best = info.get("canonical_name") or name
        return best if best else name

    # ---------- 增量学习 ----------
    def observe(self, team_id, name: str):
        """导出过程中记录 同一ID 出现的新名称变体。"""
        tid = self._norm_id(team_id)
        name = (name or "").strip()
        if not tid or not name:
            return
        with self._learned_lock:
            bucket = self.learned.setdefault(tid, {})
            bucket[name] = bucket.get(name, 0) + 1

    def _get_learned(self, tid: str) -> str:
        """返回某ID下出现次数最多的学习名称。"""
        with self._learned_lock:
            bucket = self.learned.get(tid)
            if not bucket:
                return ""
        return max(bucket, key=bucket.get) if bucket else ""

    def save_learned(self, path: str = None):
        """把增量学习结果合并写回 seed 文件（可选，默认不从导出器调用）。"""
        if not self.learned:
            return
        with self._learned_lock:
            new_entries = dict(self.learned)
        save_path = path or self.seed_path
        merged = dict(self.seed)
        for tid, names in new_entries.items():
            if tid in merged:
                merged[tid]["name_variants"] = {
                    **(merged[tid].get("name_variants") or {}),
                    **names,
                }
            else:
                canonical = max(names, key=names.get)
                merged[tid] = {
                    "canonical_name": canonical,
                    "occurrence_count": sum(names.values()),
                    "name_variants": names,
                }
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def _norm_id(team_id) -> str:
        if team_id is None:
            return ""
        s = str(team_id).strip()
        if s == "0":
            return ""
        return s

    @property
    def size(self) -> int:
        return len(self.seed)


# 单例（简单缓存，供导出器复用）
_default_instance = None
_default_instance_lock = threading.Lock()


def get_team_master(seed_path: str = None) -> TeamMaster:
    global _default_instance
    if seed_path is None:
        with _default_instance_lock:
            if _default_instance is None:
                _default_instance = TeamMaster()
            return _default_instance
    return TeamMaster(seed_path)