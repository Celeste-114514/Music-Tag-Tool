# -*- coding: utf-8 -*-
"""数据源 Provider：统一从 Apple Music(iTunes Search) 和 MusicBrainz
查询曲目标签，返回统一 entry 字典（键同 model.FIELDS）。

- Apple Music：iTunes Search API（无需 key，JP/US 双语，带 URL 缓存 + 限速）。
- MusicBrainz：open API（需 UA，限速 ~1 req/s，无 key）。

统一返回的 entry 字典（空字段 = 没查到）：
  {title, artist, album, album_artist, genre, date, track, disc,
   composer, comment}
"""
import json, io, os, re, time, urllib.request, urllib.parse, urllib.error

UA = "MusicTagTool/1.0 (music metadata enrichment)"

JP2EN = {
    "ロック": "Rock", "J-Pop": "J-Pop", "ポップ": "Pop", "オルタナティブ": "Alternative",
    "アダルト・アルタナティブ": "Adult Alternative", "メタル": "Metal", "テレビゲーム": "Video Game",
    "ビデオゲーム": "Video Game", "サウンドトラック": "Soundtrack", "クラシック": "Classical",
    "エレクトロニカ": "Electronica", "エレクトロニック": "Electronic", "アニメ": "Anime",
    "ジャズ": "Jazz", "ヒップホップ/ラップ": "Hip-Hop/Rap", "ソウル/R&B": "R&B/Soul",
    "フォーク": "Folk", "カントリー": "Country", "ニュー・ウェーブ": "New Wave",
    "インディー・ロック": "Indie Rock", "オルタナティブ・ロック": "Alternative Rock",
    "歌謡曲": "Kayokyoku", "演歌": "Enka", "テクノ": "Techno", "ハウス": "House",
    "韓国ポップ": "K-Pop", "中国語ポップ/ロック": "Cantopop/Mandopop", "ラテン": "Latin",
    "レゲエ": "Reggae", "プログレロック / アートロック": "Prog-Rock/Art Rock",
    "プログレッシブ・ロック": "Progressive Rock", "ワールド": "Worldwide", "ブルース": "Blues",
    "ファンク": "Funk", "ゴスペル": "Gospel", "ケルト": "Celtic", "DJミックス": "DJ Mix",
    "キッズ・ファミリー": "Children's Music", "サウンドトラック": "Soundtrack",
    "オーディオブック": "Audio Books", "ヒップホップ/ラップ": "Hip-Hop/Rap",
    "R&B／ソウル": "R&B/Soul", "ダンス": "Dance", "エレクトロニック": "Electronic",
    "レゲエ": "Reggae", "演芸・お笑い": "Comedy", "プレイリスト": "Playlists",
}

# 中国区(CN)常见中文流派名 -> 英文
CN2EN = {
    "流行音乐": "Pop", "国语流行": "Mandopop", "华语流行": "Mandopop", "粤语流行": "Cantopop",
    "摇滚": "Rock", "独立摇滚": "Indie Rock", "另类音乐": "Alternative", "另类摇滚": "Alternative Rock",
    "爵士乐": "Jazz", "古典音乐": "Classical", "电子音乐": "Electronic", "舞曲": "Dance",
    "嘻哈/说唱": "Hip-Hop/Rap", "说唱": "Hip-Hop/Rap", "R&B/灵魂乐": "R&B/Soul", "灵魂乐": "R&B/Soul",
    "民谣": "Folk", "乡村音乐": "Country", "金属音乐": "Metal", "重金属": "Metal",
    "电影原声": "Soundtrack", "原声带": "Soundtrack", "电视原声": "Soundtrack",
    "动漫原声": "Anime", "动画原声": "Anime", "日韩流行": "J-Pop/K-Pop", "日语流行": "J-Pop",
    "K-Pop": "K-Pop", "韩国流行": "K-Pop", "拉丁音乐": "Latin", "雷鬼": "Reggae",
    "布鲁斯": "Blues", "放克": "Funk", "新世纪音乐": "New Age", "世界音乐": "Worldwide",
    "儿童音乐": "Children's Music", "喜剧": "Comedy", "有声读物": "Audio Books", "宗教音乐": "Christian",
}



def _norm(s):
    s = re.sub(r"[\s\-–—_・,，、&／/]+", "", (s or "").lower())
    return s


def _has_cjk(s):
    return any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff' for c in (s or ""))


class _HTTP:
    """带磁盘缓存的 HTTP JSON 拉取（可选缓存文件），含简单限速。"""
    _last = [0.0]

    def __init__(self, cache_dir=None, min_interval=0.4):
        self.cache_dir = cache_dir
        self.cache = {}
        self.min_interval = min_interval
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            self._load()

    def _load(self):
        p = os.path.join(self.cache_dir, "http_cache.json")
        if os.path.exists(p):
            try:
                self.cache = json.load(open(p, encoding="utf-8"))
            except Exception:
                self.cache = {}

    def _save(self):
        if self.cache_dir:
            p = os.path.join(self.cache_dir, "http_cache.json.tmp")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False)
            os.replace(p, p[:-4])

    def _throttle(self):
        gap = time.time() - _HTTP._last[0]
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        _HTTP._last[0] = time.time()

    def get_json(self, url, retries=2):
        if url in self.cache:
            return self.cache[url]
        for i in range(retries + 1):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = r.read().decode("utf-8")
                parsed = json.loads(data)
                self.cache[url] = parsed
                self._save()
                return parsed
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    time.sleep(1.5 * (i + 1)); continue
                if i >= retries:
                    self.cache[url] = None; self._save(); return None
                time.sleep(1.0 * (i + 1))
            except Exception:
                if i >= retries:
                    self.cache[url] = None; self._save(); return None
                time.sleep(1.0 * (i + 1))
        return None


class AppleMusicProvider:
    name = "Apple Music"
    source_tag = "apple"

    def __init__(self, cache_dir=None):
        self.http = _HTTP(cache_dir)

    # --- 匹配 ---
    def _artist_ok(self, local, cand):
        L, C = _norm(local), _norm(cand)
        if not L or not C:
            return False
        if L == C:
            return True
        lpart = {x for x in re.split(r"[,&＋x×・/、+&~]", L) if len(x) >= 2}
        cpart = {x for x in re.split(r"[,&＋x×・/、+&~]", C) if len(x) >= 2}
        if lpart & cpart:
            return True
        romaji = [("椎名林檎", "sheenaringo"), ("宇多田", "hikaruutada"), ("東京事変", "tokyoincidents"),
                  ("宮本浩次", "miyamotokoji"), ("浮雲", "ukigumo"), ("中田ヤスタカ", "nakatayasutaka")]
        for ja, ro in romaji:
            if _norm(ja) in L and _norm(ro) in C:
                return True
        if len(L) >= 3 and (L in C or C in L):
            return True
        return False

    def _title_ok(self, cand, local):
        a, b = _norm(cand), _norm(local)
        if not a or not b:
            return False
        if a == b:
            return True
        # 去尾部 (ver./feat./[…] ) 后缀再比
        def core(x):
            x = re.sub(r"feat.*$", "", x)
            x = re.sub(r"[（(].*?[）)]$", "", x)
            x = re.sub(r"\[.*?\]$", "", x)
            x = re.sub(r"ver\.?\s*album\s*$", "", x)
            return _norm(x)
        return core(cand) == core(local)

    def search(self, artist, title, album=None, limit=12, storefronts=None):
        """查 Apple，返回最佳 entry 或 None。
        storefronts：按优先级尝试的店区，默认 CJK -> CN/JP/US，否则 US/CN/JP。
        （查询阶段不下载封面——封面由外部 CelesteMusicPlayer 等处理。）"""
        term = f"{title} {artist}".strip()
        areas = storefronts or (["CN", "JP", "US"] if _has_cjk(term) else ["US", "CN", "JP"])
        for c in areas:
            url = ("https://itunes.apple.com/search?" + urllib.parse.urlencode(
                {"term": term, "entity": "song", "limit": str(limit), "country": c}))
            d = self.http.get_json(url)
            if not d or d.get("resultCount", 0) == 0:
                continue
            best = None
            for it in d.get("results", []):
                if it.get("wrapperType") != "track":
                    continue
                if not self._title_ok(it.get("trackName", ""), title):
                    continue
                if not self._artist_ok(artist, it.get("artistName", "")):
                    continue
                if best is None:
                    best = it
            if best:
                return self._to_entry(best, c)
        return None

    def _to_entry(self, it, country):
        g = it.get("primaryGenreName", "")
        if country == "JP" and g:
            g = JP2EN.get(g, g)
        elif country == "CN" and g:
            g = CN2EN.get(g, g)
        return {
            "title": it.get("trackName", ""),
            "artist": it.get("artistName", ""),
            "album": it.get("collectionName", ""),
            "album_artist": it.get("collectionArtistName", "") or it.get("artistName", ""),
            "genre": g,
            "date": (it.get("releaseDate", "") or "")[:4],   # 取年份
            "track": str(it.get("trackNumber", "")) if it.get("trackNumber") else "",
            "disc": str(it.get("discNumber", "")) if it.get("discNumber") else "",
            "composer": it.get("composerName", "") or "",
            "comment": "",
        }


class MusicBrainzProvider:
    name = "MusicBrainz"
    source_tag = "mb"

    def __init__(self, cache_dir=None):
        self.base = "https://musicbrainz.org/ws/2"
        self.http = _HTTP(cache_dir, min_interval=1.2)  # MB 限速 1 req/s

    def _recording_search(self, artist, title):
        q = f'recording:"{title}" AND artist:"{artist}"'
        url = self.base + "/recording?" + urllib.parse.urlencode(
            {"query": q, "fmt": "json", "limit": "10"})
        d = self.http.get_json(url)
        return (d or {}).get("recordings", [])

    def search(self, artist, title, album=None, limit=12):
        recs = self._recording_search(artist, title)
        if not recs:
            return None
        # 选最相关（artist 匹配 + title 接近）
        best_rel = None
        for rec in recs:
            for rel in rec.get("releases", [])[:3]:
                entry = self._release_to_entry(rel)
                if not entry:
                    continue
                best_rel = entry
                break
            if best_rel:
                break
        best_rel.pop("_mb_release_id", None)
        return best_rel

    def _release_to_entry(self, rel):
        if not rel or not rel.get("id"):
            return None
        artist_name = ""
        ac = rel.get("artist-credit") or []
        if ac:
            parts = []
            for item in ac:
                parts.append(item.get("name", ""))
            artist_name = "".join(parts)
        date = (rel.get("date", "") or "")[:4]
        track_no = disc_no = ""
        mediums = rel.get("mediums") or []
        if mediums:
            m = mediums[0]
            tracks = m.get("track") or []
            if tracks:
                track_no = str(tracks[0].get("number", "") or "")
            disc_no = str(m.get("position", "") or "")
        genre = ""
        relg = rel.get("release-group") or {}
        tags = relg.get("tags") or []
        if tags:
            tags = sorted(tags, key=lambda t: t.get("count", 0), reverse=True)
            genre = tags[0].get("name", "")
        return {
            "title": rel.get("title", ""),
            "artist": artist_name,
            "album": rel.get("title", ""),
            "album_artist": artist_name,
            "genre": genre or "",
            "date": date,
            "track": track_no,
            "disc": disc_no,
            "composer": "",
            "comment": "",
        }
