"""Tests of the provider, loaded by a real server."""

import math
from array import array
from itertools import pairwise

import pytest
from music_assistant_models.enums import MediaType, ProviderTier
from music_assistant_models.media_items import BrowseFolder, Track

from music_assistant.mass import MusicAssistant
from music_assistant.models.music_provider import MusicProvider
from tests import DOMAIN

SAMPLE_RATE = 44100
FULL_SCALE = 32767
# track id: name, album, duration in seconds, (left, right) channels, pitch in Hz
TRACKS = {
    "left": ("Left channel", "Speaker check", 10, (True, False), 440),
    "right": ("Right channel", "Speaker check", 10, (False, True), 440),
    "both": ("Both channels", "Speaker check", 10, (True, True), 440),
    "tone_100": ("Tone 100 Hz", "Tones and noise", 20, (True, True), 100),
    "tone_440": ("Tone 440 Hz", "Tones and noise", 20, (True, True), 440),
    "tone_1k": ("Tone 1 kHz", "Tones and noise", 20, (True, True), 1000),
    "tone_10k": ("Tone 10 kHz", "Tones and noise", 20, (True, True), 10000),
    "sweep": ("Sweep 20 Hz to 20 kHz", "Tones and noise", 30, (True, True), None),
    "pink_noise": ("Pink noise", "Tones and noise", 30, (True, True), None),
}


@pytest.fixture
async def provider(mass: MusicAssistant) -> MusicProvider:
    """Return the provider, added to the server."""
    step = await mass.config.setup_provider(DOMAIN)
    assert step.result is not None
    provider = mass.get_provider(step.result["instance_id"])
    assert isinstance(provider, MusicProvider)
    return provider


async def test_provider_loads(mass: MusicAssistant) -> None:
    """The server loads the provider from this repository as a community provider."""
    assert mass.get_provider_manifest(DOMAIN).tier == ProviderTier.COMMUNITY


async def test_library(provider: MusicProvider) -> None:
    """The library holds every track, numbered within its album."""
    tracks = [track async for track in provider.get_library_tracks()]
    assert {track.item_id: track.name for track in tracks} == {
        track_id: name for track_id, (name, *_) in TRACKS.items()
    }
    for track in tracks:
        _, album_name, duration, *_ = TRACKS[track.item_id]
        assert track.album is not None
        assert track.album.name == album_name
        assert track.duration == duration
    albums = [album async for album in provider.get_library_albums()]
    assert [album.name for album in albums] == ["Speaker check", "Tones and noise"]
    for album in albums:
        album_tracks = await provider.get_album_tracks(album.item_id)
        assert [track.track_number for track in album_tracks] == list(
            range(1, len(album_tracks) + 1)
        )
        assert [track.item_id for track in album_tracks] == [
            track_id for track_id, (_, name, *_) in TRACKS.items() if name == album.name
        ]


async def test_search(provider: MusicProvider) -> None:
    """A search finds tracks and albums by a part of their name, in any case."""
    result = await provider.search("TONE", [MediaType.TRACK, MediaType.ALBUM])
    assert [track.name for track in result.tracks] == [
        "Tone 100 Hz",
        "Tone 440 Hz",
        "Tone 1 kHz",
        "Tone 10 kHz",
    ]
    assert [album.name for album in result.albums] == ["Tones and noise"]
    result = await provider.search("speaker", [MediaType.TRACK, MediaType.ALBUM])
    assert result.tracks == []
    assert [album.name for album in result.albums] == ["Speaker check"]


async def test_browse(provider: MusicProvider) -> None:
    """The tracks can be browsed."""
    root = await provider.browse(f"{provider.instance_id}://")
    folders = {item.item_id: item for item in root if isinstance(item, BrowseFolder)}
    assert set(folders) == {"artists", "albums", "tracks"}
    tracks = await provider.browse(folders["tracks"].path)
    assert {item.item_id for item in tracks} == set(TRACKS)


@pytest.mark.parametrize("track_id", TRACKS)
async def test_audio(provider: MusicProvider, track_id: str) -> None:
    """A track plays for its duration, on its channels, at a safe level, without clicks."""
    _, _, duration, (left, right), pitch = TRACKS[track_id]
    track = await provider.get_track(track_id)
    assert isinstance(track, Track)
    channels = await _stream(provider, track_id)

    for channel, plays in zip(channels, (left, right), strict=True):
        assert len(channel) == duration * SAMPLE_RATE
        if not plays:
            assert not any(channel), "a channel that should be silent plays"
            continue
        peak = max(abs(sample) for sample in channel)
        # never above -6 dBFS
        assert peak <= FULL_SCALE * 10 ** (-6 / 20)
        if pitch is not None or track_id == "sweep":
            # the tones and the sweep peak at -18 dBFS
            assert _db(peak) == pytest.approx(-18, abs=0.1)
        else:
            # the noise averages -24 dBFS
            assert _db(_rms(channel)) == pytest.approx(-24, abs=1)
        # it fades in and out
        assert abs(channel[0]) < FULL_SCALE / 1000
        assert abs(channel[-1]) < FULL_SCALE / 100
        if pitch is not None:
            # the middle second has the pitch of the tone
            middle = channel[SAMPLE_RATE * (duration // 2) :][:SAMPLE_RATE]
            assert _crossings(middle) / 2 == pytest.approx(pitch, abs=1)


async def test_level_is_kept(mass: MusicAssistant, provider: MusicProvider) -> None:
    """The server does not raise or lower the level of a track to match other music."""
    details = await provider.get_stream_details("tone_10k", MediaType.TRACK)
    assert mass.streams.source_normalizes_audio(details)


async def test_sweep_rises(provider: MusicProvider) -> None:
    """The sweep starts low and ends high."""
    left, _ = await _stream(provider, "sweep")
    first, last = left[:SAMPLE_RATE], left[-SAMPLE_RATE:]
    assert _crossings(first) / 2 < 30
    assert _crossings(last) / 2 > 15000


async def test_seek(provider: MusicProvider) -> None:
    """Playback that starts later in a track plays the rest of it, with a fade in."""
    left, _ = await _stream(provider, "tone_1k", seek_position=15)
    assert len(left) == 5 * SAMPLE_RATE
    assert abs(left[0]) < FULL_SCALE / 1000
    assert _db(max(abs(sample) for sample in left)) == pytest.approx(-18, abs=0.1)


async def _stream(
    provider: MusicProvider, track_id: str, seek_position: int = 0
) -> tuple[array[int], array[int]]:
    """Return the audio of a track as the samples of its left and its right channel."""
    details = await provider.get_stream_details(track_id, MediaType.TRACK)
    assert details.audio_format.sample_rate == SAMPLE_RATE
    assert details.audio_format.bit_depth == 16
    assert details.audio_format.channels == 2
    audio = array("h")
    async for chunk in provider.get_audio_stream(details, seek_position):
        audio.frombytes(chunk)
    return audio[0::2], audio[1::2]


def _db(level: float) -> float:
    """Return a level in dB relative to full scale."""
    return 20 * math.log10(level / FULL_SCALE)


def _rms(samples: array[int]) -> float:
    """Return the root mean square of samples."""
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _crossings(samples: array[int]) -> int:
    """Return how often samples change sign."""
    return sum((a < 0) != (b < 0) for a, b in pairwise(samples))
