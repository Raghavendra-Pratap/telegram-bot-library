"""
Test script for the name parser
"""
from name_parser import NameParser, strip_clipmate_movie_prefix

parser = NameParser()

CLIPMATE_FILES = [
    (
        "@Clipmate_Movie_Check_2021_1080p_HEVC_HDRip_UNCUT_South_Movie_Dual.mkv",
        "Check",
        "2021",
    ),
    (
        "@Clipmate_Movie_Pushpa:_The_Rise_Part_1_2021_720p_HDRip_UNCUT_South.mkv",
        "Pushpa: The Rise Part 1",
        "2021",
    ),
    (
        "Aclipmate Movie Check 2021 720p.mkv",
        "Check",
        "2021",
    ),
]


def test_clipmate_prefix_strip() -> None:
    raw = "@Clipmate_Movie_Check_2021.mkv"
    assert strip_clipmate_movie_prefix(raw).lower().startswith("check")
    for filename, expected_title, expected_year in CLIPMATE_FILES:
        result = parser.parse_name(filename)
        assert expected_title.lower() in (result["name"] or "").lower(), (
            f"{filename!r} -> {result['name']!r}, want {expected_title!r}"
        )
        assert result.get("year") == expected_year, (
            f"{filename!r} year {result.get('year')!r}, want {expected_year!r}"
        )


test_files = [
    "CIA.Americas.Secret.Warriors.1of3.x264.AC3.MVGroup.org.mkv",
    "CIA.Americas.Secret.Warriors.2of3.x264.AC3.MVGroup.org.mkv",
    "CIA.Americas.Secret.Warriors.3of3.x264.AC3.MVGroup.org.mkv",
    "Bono.Stories.Of.Surrender.2025.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4",
    "Dont.Turn.Out.the.Lights.2023.1080p.BluRay.x265.AAC.5.1-SWAXXON.mkv",
    "Fight.Club.10th.Anniversary.Edition.1999.1080p.BrRip.x264.YIFY.mp4",
    "Insomnia.2002.1080p.BluRay.x264.YIFY.mp4",
    "Jolly LLB (2025) Hindi 1080p WEBRip x264 DD 5.1 ESub.mkv",
    "Memoir of a Snail (2024) 1080p WEBRip x265 ENG EAC3 Sub ita - iDN_CreW.mkv",
    "Mr.And.Mrs.55.1955.1080p.AMZN.WEB-Rip.DD+2.1.HEVC-DDR[EtHD].mkv",
    "Om Dar-B-Dar (1988) _ Full Movie HD (1080p).mkv",
    "Puzzle.2018.1080p.WEBRip.x264-[YTS.AM].mp4",
    "Shree.420.1955.720p.WEBRip.x264.AAC-[YTS.MX].mp4",
    "Steve (2025) 1080p x265 ita eng ac3 sub ita eng nueng - MIRCrew.mkv",
    "Stolen.2023.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4",
    "The Baltimorons 2025 1080p BluRay HEVC x265 5.1 BONE.mkv",
    "The Fifth Element 1997 Remastered 1080p BluRay HEVC x265 5.1 BONE.mkv",
    "The Lost Bus (2025) Eng 1080p AV1 WEBRip DD 5.1 ESub.mkv",
    "The Town 2010 [Bolly4u.wiki] Dual Audio BRRip 720p 950MB.mkv",
    "The.Autopsy.of.Jane.Doe.2016.720p.BluRay.X264-AMIABLE.srt",
    "The.Autopsy.Of.Jane.Doe.2016.1080p.BluRay.x264-[YTS.AG].mp4",
    "The.Brutalist.2024.1080p.BluRay.AV1.Opus.5.1-SWAXXON.mkv",
    "The.Devils.Advocate.1997.1080p.BluRay.x264.YIFY.mp4",
    "The.Mosaic.Church.2025.1080p.WEBRip.x264.AAC5.1-LAMA.mp4",
    "The.Usual.Suspects.1995.1080p.BluRay.x264-[YTS.AM].mp4",
    "Twelve Monkeys 1995 Remastered 1080p BluRay HEVC x265 5.1 BONE.mkv"
]

if __name__ == "__main__":
    test_clipmate_prefix_strip()
    print("clipmate prefix tests OK\n")

    print("=" * 80)
    print("Name Parser Test Results")
    print("=" * 80)

    for filename in test_files:
        result = parser.parse_name(filename)
        display_name = parser.format_display_name(result)

        print(f"\nOriginal: {filename}")
        print(f"Parsed:   {result['name']}")
        print(f"Year:     {result['year']}")
        print(f"Part:     {result['part_info']}")
        print(f"Display:  {display_name}")
        print(f"Confidence: {result['confidence']}")
        print("-" * 80)
