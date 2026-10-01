from app.graph.narrative import IncrementalSegmenter


def collect(chunks):
    seg = IncrementalSegmenter()
    out = []
    for c in chunks:
        out.extend(seg.feed(c))
    out.extend(seg.flush())
    return out


def test_marker_split_across_chunks():
    out = collect(["你推开门。[[np", "c:guard]]站住！[[/n", "pc]]他盯着你。"])
    assert out == [("gm", "你推开门。"), ("npc:guard", "站住！"), ("gm", "他盯着你。")]


def test_plain_text_streams_immediately():
    out = collect(["第一句。", "第二句。"])
    assert out == [("gm", "第一句。"), ("gm", "第二句。")]


def test_holdback_only_prefix():
    seg = IncrementalSegmenter()
    assert seg.feed("他说[") == [("gm", "他说")]           # "[" 可能是标记前缀 → 扣留
    assert seg.feed("[不是标记]") == [("gm", "[[不是标记]")]  # 补全后不是标记 → 全部放出


def test_multiple_markers_one_chunk():
    out = collect(["[[npc:a]]一[[/npc]]中[[npc:b]]二[[/npc]]尾"])
    assert out == [("npc:a", "一"), ("gm", "中"), ("npc:b", "二"), ("gm", "尾")]


def test_npc_text_emits_before_close_marker():
    seg = IncrementalSegmenter()
    assert seg.feed("[[npc:ghost]]说了半句") == [("npc:ghost", "说了半句")]


def test_flush_releases_leftover_buffer():
    seg = IncrementalSegmenter()
    assert seg.feed("他说[[npc") == [("gm", "他说")]
    assert seg.flush() == [("gm", "[[npc")]    # 截断在标记前缀处：残余缓冲兜底放出
    assert seg.flush() == []
