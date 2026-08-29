from app.utils.mime import is_video, is_audio, is_image, get_file_type_category
from app.upload.progress import UploadProgressTracker


def test_media_classification():
    assert is_video("movie.mp4") is True
    assert is_video("clip.mkv") is True
    assert is_video("video.webm") is True
    assert is_video("song.mp3") is False

    assert is_audio("track.mp3") is True
    assert is_audio("voice.ogg") is True
    assert is_audio("sound.flac") is True
    assert is_audio("doc.pdf") is False

    assert is_image("photo.jpg") is True
    assert is_image("logo.png") is True

    assert get_file_type_category("archive.zip") == "ARCHIVE"
    assert get_file_type_category("document.pdf") == "DOCUMENT"
    assert get_file_type_category("movie.mp4") == "VIDEO"
    assert get_file_type_category("song.mp3") == "AUDIO"


def test_upload_progress_tracker():
    tracker = UploadProgressTracker("data.zip", total_bytes=10000, min_interval=0.0)
    should_update = tracker.update(5000, 10000)
    assert tracker.percentage == 50.0
    msg = tracker.format_upload_message()
    assert "data.zip" in msg
    assert "50%" in msg
