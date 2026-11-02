"""
KdocsEpisodeNotify 纯逻辑单元测试。

依赖 MoviePilot 宿主环境（插件以 app.plugins.<plugin_id> 路径导入）：
    <MoviePilot>/.venv/bin/python -m pytest tests/v3/kdocsepisodenotify
"""

import pytest

from app.plugins.kdocsepisodenotify import (
    build_item_key,
    escape_html,
    parse_header_category,
    parse_item_row,
    parse_sheet_rows,
    pick_monthly_sheet,
    select_new_items,
    split_message,
)

# 真实文档中出现过的条目行，覆盖各类写法
CASE_ROWS = [
    "【4K国产剧】尚公主 (2026)[爱情 古装][孟子义 李昀锐].2160P.共40集.更新22",
    "【HD韩剧】恋爱博士 (2026)[爱情 青春][秋泳愚 金所泫 金玟锡].HD1080P.内嵌中字.共12集.更08",
    "【4K美剧】龙之家族 第三季 (2026)[动作 奇幻 冒险].2160P.HDR.DV.共8集.更新03",
    "【4K国漫】斗破苍穹 [第八季][年番4](2025).2160p.H265.[158-219集.共52集].更新217",
    "【HD综艺】我家那闺女2026[真人秀][齐思钧 陈妍希 陈瑶][附加2025].1080p.更新10-11",
    "【4K国产剧】小城良方 (2026)[剧情][肖战 倪大红 姜妍].2160P.共29集全",
]


@pytest.mark.parametrize("row", CASE_ROWS)
def test_parse_item_row_always_returns_item(row):
    item = parse_item_row(row)
    assert item is not None
    assert item.name
    assert item.raw == row


def test_parse_item_row_name_and_year():
    item = parse_item_row(CASE_ROWS[0])
    assert item.name == "尚公主"
    assert item.year == "2026"
    assert item.season is None


def test_parse_item_row_season_from_name():
    item = parse_item_row(CASE_ROWS[2])
    assert item.season == 3
    assert item.name == "龙之家族"


def test_parse_item_row_season_from_bracket():
    """「[第八季]」这种季数写在方括号里的写法也要能识别。"""
    item = parse_item_row(CASE_ROWS[3])
    assert item.name == "斗破苍穹"
    assert item.season == 8


def test_parse_item_row_without_year_still_accepted():
    """综艺行没有 (年份) 括号，靠更新痕迹判定为条目。"""
    item = parse_item_row(CASE_ROWS[4])
    assert item.name == "我家那闺女2026"
    assert item.year is None


def test_parse_item_row_total_episodes():
    """总集数只用于详情页展示，不参与提醒判定。"""
    assert parse_item_row(CASE_ROWS[0]).total == 40
    assert parse_item_row("【4K国产剧】某剧 (2026).2160P.共30集.更新25").total == 30
    assert parse_item_row("【4K国漫】牧神记 (2026).2160P.共1-156集.更新107").total == 156
    assert parse_item_row("【4K国产剧】某剧 (2026).2160P.共29集全").total == 29
    assert parse_item_row("【4K国产剧】某剧 (2026).2160P.更新05").total is None


def test_parse_item_row_rejects_non_item_rows():
    assert parse_item_row("") is None
    assert parse_item_row("【明星合集专区】👇置底查找👇") is None
    assert parse_item_row("【4K纪录片】音乐合集[26.8GB]") is None


def test_parse_header_category():
    assert parse_header_category("🟨🟩🟦丨本月更新【国产剧】丨🧡💛💚") == "国产剧"
    assert parse_header_category("本月更新【国外剧】") == "国外剧"
    assert parse_header_category("【免责声明】所有视频资源") is None


def test_item_key_ignores_punctuation_and_category():
    """去重键只看名称与季数，与分类、标点、空格无关。"""
    assert build_item_key("尚公主", None) == build_item_key("尚 公主。", 1)
    assert build_item_key("龙之家族", 3) != build_item_key("龙之家族", 1)


def test_parse_sheet_rows_only_keeps_watched_sections():
    """只收集国产剧/国外剧，动漫、综艺等区段直接被忽略。"""
    rows = [
        ("本月更新【国产剧】",),
        ("【4K国产剧】尚公主 (2026).2160P.共40集.更新22",),
        ("本月更新【国外剧】",),
        ("【HD韩剧】恋爱博士 (2026).HD1080P.共12集.更08",),
        ("本月更新【热门动漫】",),
        ("【4K国漫】牧神记 (2026).2160P.共16集.更新14",),
        ("本月更新【综艺】",),
        ("【4K综艺】中餐厅 第十季 (2026).2160P.共12期全",),
    ]
    items, headers, _ = parse_sheet_rows(rows)
    assert [item.name for item in items] == ["尚公主", "恋爱博士"]
    assert [item.category for item in items] == ["国产剧", "国外剧"]
    assert "热门动漫" in headers and "综艺" in headers


def test_parse_sheet_rows_stops_at_collection_area():
    """区段后出现无法解析的行（合集区）时立即结束，不会把合集当剧集。"""
    rows = [
        ("本月更新【国产剧】",),
        ("【4K国产剧】尚公主 (2026).2160P.共40集.更新22",),
        ("【4K国产剧】知否知否应是绿肥红瘦 (2018).2160P.共73集全",),
        ("【4K纪录片】音乐合集[26.8GB]",),
        ("【4K国产剧】晚到的行不会被解析",),
    ]
    items, _, _ = parse_sheet_rows(rows)
    assert [item.name for item in items] == ["尚公主", "知否知否应是绿肥红瘦"]


def test_parse_sheet_rows_ignores_non_drama_tags():
    """【4K游戏】之类标签直接忽略。"""
    rows = [
        ("本月更新【国外剧】",),
        ("【4K游戏】侠盗猎车手6（2026）2160P.内嵌中字.[4.80GB]",),
        ("【4K美剧】幻视任务 (2026).2160P.共8集.更新06",),
    ]
    items, _, skipped = parse_sheet_rows(rows)
    assert [item.name for item in items] == ["幻视任务"]
    assert skipped == 1


def test_new_drama_is_reported_without_any_subscription():
    """只认插件自身的已提醒记录：没在 MoviePilot 订阅的新剧也要提醒。"""
    rows = [("本月更新【国产剧】",), (CASE_ROWS[0],), (CASE_ROWS[5],)]
    items, _, _ = parse_sheet_rows(rows)
    pending = select_new_items(items, {}, {"国产剧": "2026-11-01 21:01:00"})
    assert [item.name for item in pending] == ["尚公主", "小城良方"]


def test_reminded_drama_never_repeats():
    """已提醒过的剧继续更新、或换个分类出现，都不再提醒。"""
    drama = parse_item_row(CASE_ROWS[0])
    state = {drama.key: {"name": "尚公主", "category": "国产剧"}}
    later = parse_item_row("【4K国产剧】尚公主 (2026).2160P.共40集.更新30")
    assert select_new_items([later], state, {"国产剧": "t"}) == []
    moved = parse_item_row(CASE_ROWS[0])
    moved.category = "完结剧集"
    assert select_new_items([moved], state, {"完结剧集": "t"}) == []


def test_first_scan_is_silent_then_reports_new():
    """首轮扫描只建基线，之后新增的才提醒。"""
    first = parse_item_row(CASE_ROWS[0])
    first.category = "国产剧"
    assert select_new_items([first], {}, {}) == []
    second = parse_item_row(CASE_ROWS[5])
    second.category = "国产剧"
    pending = select_new_items([first, second], {first.key: {}}, {"国产剧": "t"})
    assert [item.name for item in pending] == ["小城良方"]


def test_pick_monthly_sheet():
    names = ["2026-11月多网盘更新 ", "2026-10月多网盘更新", "电影院线", "2026-1月多网盘更新"]
    assert pick_monthly_sheet(names) == "2026-11月多网盘更新 "
    assert pick_monthly_sheet(["电影院线"]) == "电影院线"
    assert pick_monthly_sheet([]) is None


def test_split_message_keeps_lines():
    text = "\n".join(f"第{i}行" for i in range(200))
    chunks = split_message(text, limit=50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert "\n".join(chunks) == text


def test_escape_html():
    assert escape_html("a<b>&c") == "a&lt;b&gt;&amp;c"
    assert "&lt;" not in escape_html("正常名称")
