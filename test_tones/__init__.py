"""
Test tones for Music Assistant.

A music source that generates its own audio, so it works without an account, a file or a network:
a tone on each channel, steady tones, a sweep and pink noise, to check speakers with. Each track
plays at a moderate level with a short fade in and out.
"""

from __future__ import annotations

import asyncio
import math
import random
from array import array
from collections.abc import AsyncGenerator, Callable, Iterator
from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING

from music_assistant_models.enums import ContentType, MediaType, ProviderFeature, StreamType
from music_assistant_models.errors import MediaNotFoundError
from music_assistant_models.media_items import (
    Album,
    Artist,
    AudioFormat,
    ProviderMapping,
    SearchResults,
    Track,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails

from music_assistant.models.music_provider import MusicProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

SUPPORTED_FEATURES = {
    ProviderFeature.BROWSE,
    ProviderFeature.SEARCH,
    ProviderFeature.LIBRARY_ARTISTS,
    ProviderFeature.LIBRARY_ALBUMS,
    ProviderFeature.LIBRARY_TRACKS,
}

SAMPLE_RATE = 44100
# the peak of the tones and the sweep: -18 dBFS, the alignment level of broadcast test tones
TONE_LEVEL = 10 ** (-18 / 20)
# the average (RMS) level of the pink noise, -24 dBFS
NOISE_LEVEL = 10 ** (-24 / 20)
# no sample goes above this, -6 dBFS; only a rare peak of the noise comes near it
MAX_LEVEL = 10 ** (-6 / 20)
FADE_SECONDS = 0.5
SWEEP_LOW, SWEEP_HIGH = 20, 20000


@dataclass(frozen=True)
class Signal:
    """What a track plays, on which channels and for how long."""

    name: str
    album_id: str
    duration: int
    # yields the samples of one channel, between -1 and 1, from the frame it is given
    wave: Callable[[int], Iterator[float]]
    left: bool = True
    right: bool = True


ARTIST_ID = "test_tones"
# album id: name
ALBUMS = {
    "channels": "Speaker check",
    "tones": "Tones and noise",
}
# track id: what it plays, in the order of the albums
SIGNALS = {
    "left": Signal("Left channel", "channels", 10, lambda first: _tone(440, first), right=False),
    "right": Signal("Right channel", "channels", 10, lambda first: _tone(440, first), left=False),
    "both": Signal("Both channels", "channels", 10, lambda first: _tone(440, first)),
    "tone_100": Signal("Tone 100 Hz", "tones", 20, lambda first: _tone(100, first)),
    "tone_440": Signal("Tone 440 Hz", "tones", 20, lambda first: _tone(440, first)),
    "tone_1k": Signal("Tone 1 kHz", "tones", 20, lambda first: _tone(1000, first)),
    "tone_10k": Signal("Tone 10 kHz", "tones", 20, lambda first: _tone(10000, first)),
    "sweep": Signal("Sweep 20 Hz to 20 kHz", "tones", 30, lambda first: _sweep(30, first)),
    "pink_noise": Signal("Pink noise", "tones", 30, lambda _: _pink_noise()),
}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize the provider for one settings entry."""
    return TestTonesProvider(mass, manifest, config, SUPPORTED_FEATURES)


class TestTonesProvider(MusicProvider):
    """A music source with test tones for speakers."""

    @property
    def is_streaming_provider(self) -> bool:
        """Return False: the library of this source holds everything it offers."""
        return False

    def delivers_normalized_audio(self, streamdetails: StreamDetails) -> bool:
        """Return True: the level of a test tone is part of the test, the server keeps it."""
        return True

    async def search(
        self, search_query: str, media_types: list[MediaType], limit: int = 5
    ) -> SearchResults:
        """
        Return the items whose name contains the search query.

        :param search_query: The text to search for.
        :param media_types: The media types to include.
        :param limit: The maximum number of items per media type.
        """
        query = search_query.lower()
        result = SearchResults()
        if MediaType.ARTIST in media_types:
            artist = self._artist()
            result.artists = [artist] if query in artist.name.lower() else []
        if MediaType.ALBUM in media_types:
            albums = [self._album(album_id) for album_id in ALBUMS]
            result.albums = [album for album in albums if query in album.name.lower()][:limit]
        if MediaType.TRACK in media_types:
            tracks = [self._track(track_id) for track_id in SIGNALS]
            result.tracks = [track for track in tracks if query in track.name.lower()][:limit]
        return result

    async def get_library_artists(self) -> AsyncGenerator[Artist]:
        """Return the artists of this source."""
        yield self._artist()

    async def get_library_albums(self) -> AsyncGenerator[Album]:
        """Return the albums of this source."""
        for album_id in ALBUMS:
            yield self._album(album_id)

    async def get_library_tracks(self) -> AsyncGenerator[Track]:
        """Return the tracks of this source."""
        for track_id in SIGNALS:
            yield self._track(track_id)

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Return the artist with the given id."""
        if prov_artist_id != ARTIST_ID:
            raise MediaNotFoundError(f"Artist {prov_artist_id} not found")
        return self._artist()

    async def get_album(self, prov_album_id: str) -> Album:
        """Return the album with the given id."""
        if prov_album_id not in ALBUMS:
            raise MediaNotFoundError(f"Album {prov_album_id} not found")
        return self._album(prov_album_id)

    async def get_track(self, prov_track_id: str) -> Track:
        """Return the track with the given id."""
        if prov_track_id not in SIGNALS:
            raise MediaNotFoundError(f"Track {prov_track_id} not found")
        return self._track(prov_track_id)

    async def get_album_tracks(self, prov_album_id: str) -> list[Track]:
        """Return the tracks of the album with the given id."""
        if prov_album_id not in ALBUMS:
            raise MediaNotFoundError(f"Album {prov_album_id} not found")
        return [
            self._track(track_id)
            for track_id, signal in SIGNALS.items()
            if signal.album_id == prov_album_id
        ]

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Return how the server gets the audio of a track."""
        if item_id not in SIGNALS:
            raise MediaNotFoundError(f"Track {item_id} not found")
        return StreamDetails(
            provider=self.instance_id,
            item_id=item_id,
            audio_format=AudioFormat(
                content_type=ContentType.PCM_S16LE,
                sample_rate=SAMPLE_RATE,
                bit_depth=16,
                channels=2,
            ),
            media_type=MediaType.TRACK,
            stream_type=StreamType.CUSTOM,
            duration=SIGNALS[item_id].duration,
            allow_seek=True,
            can_seek=True,
        )

    async def get_audio_stream(
        self, streamdetails: StreamDetails, seek_position: int = 0
    ) -> AsyncGenerator[bytes]:
        """
        Yield the audio of a track as 16-bit stereo PCM, one second per chunk.

        :param streamdetails: What get_stream_details returned for the track.
        :param seek_position: The second to start at.
        """
        seconds = _render(SIGNALS[streamdetails.item_id], seek_position)
        while chunk := await asyncio.to_thread(next, seconds, b""):
            yield chunk

    def _artist(self) -> Artist:
        """Return the artist of this source."""
        return Artist(
            item_id=ARTIST_ID,
            provider=self.instance_id,
            name="Test Tones",
            provider_mappings={self._mapping(ARTIST_ID)},
        )

    def _album(self, album_id: str) -> Album:
        """Return an album of this source."""
        return Album(
            item_id=album_id,
            provider=self.instance_id,
            name=ALBUMS[album_id],
            artists=UniqueList([self._artist()]),
            provider_mappings={self._mapping(album_id)},
        )

    def _track(self, track_id: str) -> Track:
        """Return a track of this source."""
        signal = SIGNALS[track_id]
        album_tracks = [key for key, item in SIGNALS.items() if item.album_id == signal.album_id]
        return Track(
            item_id=track_id,
            provider=self.instance_id,
            name=signal.name,
            duration=signal.duration,
            artists=UniqueList([self._artist()]),
            album=self._album(signal.album_id),
            disc_number=1,
            track_number=album_tracks.index(track_id) + 1,
            provider_mappings={self._mapping(track_id)},
        )

    def _mapping(self, item_id: str) -> ProviderMapping:
        """Return where an item lives on this source."""
        return ProviderMapping(
            item_id=item_id,
            provider_domain=self.domain,
            provider_instance=self.instance_id,
            audio_format=AudioFormat(
                content_type=ContentType.PCM_S16LE, sample_rate=SAMPLE_RATE, bit_depth=16
            ),
        )


def _render(signal: Signal, start: int) -> Iterator[bytes]:
    """
    Yield the audio of a track as 16-bit stereo PCM, one second at a time.

    :param signal: What the track plays.
    :param start: The second to start at.
    """
    first, last = start * SAMPLE_RATE, signal.duration * SAMPLE_RATE
    fade = FADE_SECONDS * SAMPLE_RATE
    wave = signal.wave(first)
    for second in range(start, signal.duration):
        samples = array("h")
        for frame in range(second * SAMPLE_RATE, (second + 1) * SAMPLE_RATE):
            # fades in from where playback starts, so a seek does not click either
            gain = min(1.0, (frame - first) / fade, (last - frame) / fade)
            value = max(-MAX_LEVEL, min(MAX_LEVEL, gain * next(wave)))
            sample = round(value * 32767)
            samples.extend((sample if signal.left else 0, sample if signal.right else 0))
        yield samples.tobytes()


def _tone(frequency: int, first: int) -> Iterator[float]:
    """
    Yield a steady sine tone.

    :param frequency: The pitch in Hz.
    :param first: The frame to start at.
    """
    for frame in count(first):
        yield TONE_LEVEL * math.sin(2 * math.pi * frequency * frame / SAMPLE_RATE)


def _sweep(duration: int, first: int) -> Iterator[float]:
    """
    Yield a sine that rises from SWEEP_LOW to SWEEP_HIGH Hz at the same pace per octave.

    :param duration: The length of the sweep in seconds.
    :param first: The frame to start at.
    """
    rate = math.log(SWEEP_HIGH / SWEEP_LOW) / duration
    for frame in count(first):
        seconds = frame / SAMPLE_RATE
        phase = 2 * math.pi * SWEEP_LOW * (math.exp(rate * seconds) - 1) / rate
        yield TONE_LEVEL * math.sin(phase)


def _pink_noise() -> Iterator[float]:
    """Yield pink noise: the same energy in every octave."""
    generator = random.Random()  # noqa: S311 - noise, not a secret
    b0 = b1 = b2 = 0.0
    while True:
        # Paul Kellet's filter turns white noise into pink; its output has an RMS of about 3
        white = generator.gauss()
        b0 = 0.99765 * b0 + white * 0.0990460
        b1 = 0.96300 * b1 + white * 0.2965164
        b2 = 0.57000 * b2 + white * 1.0526913
        yield NOISE_LEVEL * (b0 + b1 + b2 + white * 0.1848) / 3
