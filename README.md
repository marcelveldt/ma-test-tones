# Test Tones for Music Assistant

Test Tones adds tracks to [Music Assistant](https://music-assistant.io) that are made to check
your speakers: which one plays left and which one right, how low and how high they reach, and
whether they play at the level you expect. The tones are generated on your server while they
play: no account, no internet connection and no files.

Test Tones is made and maintained by [@marcelveldt](https://github.com/marcelveldt), not by the
Music Assistant team. Questions and problems go to the
[issues of this repository](https://github.com/marcelveldt/ma-test-tones/issues).

## What it plays

| Album | Track | Length | What you hear |
|---|---|---|---|
| Speaker check | Left channel | 10 s | A 440 Hz tone on the left channel only |
| Speaker check | Right channel | 10 s | The same tone on the right channel only |
| Speaker check | Both channels | 10 s | The same tone on both channels, from the middle between your speakers |
| Tones and noise | Tone 100 Hz | 20 s | A low hum, for a woofer or subwoofer |
| Tones and noise | Tone 440 Hz | 20 s | The A that musicians tune to |
| Tones and noise | Tone 1 kHz | 20 s | The usual reference tone |
| Tones and noise | Tone 10 kHz | 20 s | A high whistle, for a tweeter |
| Tones and noise | Sweep 20 Hz to 20 kHz | 30 s | A tone that rises from the lowest to the highest you can hear |
| Tones and noise | Pink noise | 30 s | Even noise like steady rain, to compare speakers and their volume |

Every track fades in and out in half a second, so nothing clicks. The tones and the sweep play at
-18 dBFS, the level of broadcast test tones, and the pink noise at an average of -24 dBFS: well
below the loudest a recording can be. Music Assistant plays them at this level and does not raise or
lower it to match your music.

Start with your speaker at a low volume and turn it up slowly, above all for the 10 kHz tone and
the sweep: a high tone played loud can damage a tweeter and hurt your ears. Many people stop
hearing the sweep well before 20 kHz; that is normal.

## Add it

Test Tones comes from the community catalog of Music Assistant. Everything in the community
catalog is used at your own risk.

1. Open the Marketplace in Music Assistant. An administrator enables the community catalog there
   once.
2. Find Test Tones in it and add it.
3. The albums Speaker check and Tones and noise show up in your library. Play a track on the
   speaker you want to check.

## For developers

This repository started from the
[Music Assistant community provider template](https://github.com/music-assistant/community-provider-template),
whose README explains the development container, the rules of the community catalog and how a
release reaches users. The provider is in `test_tones/`.

With [uv](https://docs.astral.sh/uv/), run the tests, the lint and the type check:

    uv sync
    uv run pytest
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy

The tests start a real Music Assistant server with the provider, play every track and check its
length, its channels, its level and its pitch. `scripts/run.sh` starts a server in dev mode with
the provider, to try it in the app at <http://localhost:8095>.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
