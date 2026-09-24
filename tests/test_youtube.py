import pytest
from unittest.mock import MagicMock, patch
from app.downloaders.youtube import YouTubeDownloader


def test_youtube_can_handle():
    dl = YouTubeDownloader()
    assert dl.can_handle("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert dl.can_handle("https://youtu.be/dQw4w9WgXcQ") is True
    assert dl.can_handle("https://music.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert dl.can_handle("https://youtube.com/shorts/abcdef12345") is True
    assert dl.can_handle("https://music.youtube.com/playlist?list=PL12345678") is True
    assert dl.can_handle("https://example.com/video.mp4") is False


@pytest.mark.asyncio
async def test_youtube_metadata_mock():
    dl = YouTubeDownloader()

    mock_info = {
        "title": "Never Gonna Give You Up",
        "duration": 213,
        "uploader": "Rick Astley",
        "filesize": 15000000,
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "vcodec": "avc1.64001F"
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_info

    with patch("yt_dlp.YoutubeDL") as MockYoutubeDL:
        MockYoutubeDL.return_value.__enter__.return_value = mock_ydl
        meta = await dl.get_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert meta.filename == "Never Gonna Give You Up.mp4"
        assert meta.filesize == 15000000
        assert meta.source_service == "YouTube"
        assert meta.extra.get("uploader") == "Rick Astley"


@pytest.mark.asyncio
async def test_youtube_music_metadata_mock():
    dl = YouTubeDownloader()

    mock_info = {
        "title": "Song Track Title",
        "duration": 180,
        "artist": "Artist Name",
        "filesize": 5000000,
        "thumbnail": "https://lh3.googleusercontent.com/...",
        "vcodec": "none"
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_info

    with patch("yt_dlp.YoutubeDL") as MockYoutubeDL:
        MockYoutubeDL.return_value.__enter__.return_value = mock_ydl
        meta = await dl.get_metadata("https://music.youtube.com/watch?v=track123")
        assert meta.filename == "Song Track Title.mp3"
        assert meta.mime_type == "audio/mpeg"
        assert meta.extra.get("is_music") is True
