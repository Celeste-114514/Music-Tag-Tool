# -*- coding: utf-8 -*-
"""统一的音频标签数据模型：定义可读写的字段及多格式(m4a/mp3/flac/ogg)映射。

各平台(Apple/MusicBrainz)查询结果都会转成这个统一结构，写标签时按字段写回。
"""

# 所有可选的标签字段（中文名 -> 内部 key）
FIELDS = [
    ("title", "标题"),
    ("artist", "歌手"),
    ("album", "专辑"),
    ("album_artist", "专辑歌手"),
    ("genre", "流派"),
    ("date", "发行日期/年份"),
    ("track", "曲目号"),
    ("disc", "碟号"),
    ("composer", "作曲"),
    ("comment", "备注"),
]

# 内部 key -> 说明
FIELD_DESC = {k: v for k, v in FIELDS}


def normalize_entry(raw):
    """把任意来源的关键字归一成 str（列表取首个/去控制字符）。"""
    def _one(v):
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            v = v[0] if v else ""
        s = str(v)
        return s.replace("\x00", " ").strip()
    return _one


class AudioTags:
    """一次标签读写操作的载体：读入现有标签，分别跟踪 provider 提供的候选值。"""

    __slots__ = ["current", "candidate", "path"]

    def __init__(self, path=""):
        self.path = path
        self.current = {k: "" for k, _ in FIELDS}   # 当前文件已有值（只读参考）
        self.candidate = {k: "" for k, _ in FIELDS}  # 平台给的建议值

    # --- 便捷读写 current ---
    def get(self, k):
        return self.current.get(k, "")

    # --- 判断某字段是否需要写入 ---
    def needs(self, k):
        """平台给了候选值，且与当前值不同（或当前为空）→ 需要写。"""
        cval = (self.current.get(k) or "").strip()
        nval = (self.candidate.get(k) or "").strip()
        if not nval:
            return False
        return nval != cval

    def plan(self, enabled):
        """返回计划写入的字段列表: [(key, 现值, 新值)]"""
        out = []
        for k, _ in FIELDS:
            if k not in enabled:
                continue
            if self.needs(k):
                out.append((k, self.current.get(k, ""), self.candidate.get(k, "")))
        return out
