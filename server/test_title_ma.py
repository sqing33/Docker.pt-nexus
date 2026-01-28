import os
import sys
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


from utils.title import upload_data_title  # noqa: E402


class TestTitleMASourcePlatform(unittest.TestCase):
    def _parse(self, title: str) -> dict:
        comps = upload_data_title(title)
        return {c["key"]: c.get("value", "") for c in comps}

    def _parse_with_mediainfo(self, title: str) -> dict:
        mediainfo_hdr = {"standard_tag": "HDR"}
        mediainfo_audio = {
            "codec": "DTS-HD MA",
            "channels": "5.1 3Audios",
            "has_atmos": False,
            "all_tracks": [
                {"codec": "DTS-HD MA", "channels": "5.1", "has_atmos": False, "audio_count": "3Audios"}
            ],
        }
        comps = upload_data_title(
            title, mediaInfo="dummy", mediainfo_hdr=mediainfo_hdr, mediainfo_audio=mediainfo_audio
        )
        return {c["key"]: c.get("value", "") for c in comps}

    def test_ma_source_platform_is_extracted(self):
        d = self._parse(
            "Father Of The Bride 2022 2160p MA WEB-DL DDP5.1 DV H 265-XXXXX"
        )
        self.assertEqual(d.get("片源平台"), "MA")
        self.assertEqual(d.get("音频编码"), "DDP 5.1")
        self.assertEqual(d.get("无法识别"), "")

    def test_audio_dts_hd_ma_does_not_trigger_ma_source_platform(self):
        d = self._parse("Some Movie 2022 2160p WEB-DL DTS-HD MA 7.1 DV H 265-XX")
        self.assertEqual(d.get("片源平台"), "")
        self.assertEqual(d.get("音频编码"), "DTS-HD MA 7.1")

    def test_both_platform_ma_and_audio_dts_hd_ma(self):
        d = self._parse("Movie 2022 2160p MA WEB-DL DTS-HD MA 7.1 DV H 265-GRP")
        self.assertEqual(d.get("片源平台"), "MA")
        self.assertEqual(d.get("音频编码"), "DTS-HD MA 7.1")
        self.assertEqual(d.get("无法识别"), "")

    def test_with_mediainfo_platform_ma_and_audio_dts_hd_ma(self):
        d = self._parse_with_mediainfo(
            "Signs 2002 2160p MA BluRay HDR x265 10bit DTS-HD MA 5.1 3Audios-CHD"
        )
        self.assertEqual(d.get("片源平台"), "MA")
        self.assertEqual(d.get("音频编码"), "DTS-HD MA 5.1 3Audios")
        self.assertEqual(d.get("无法识别"), "")


if __name__ == "__main__":
    unittest.main()
