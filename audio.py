"""Non-blocking MP3 cues through libVLC."""

import logging
from pathlib import Path

LOG = logging.getLogger("touchline")


class Audio:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.instance = None
        self.players = {}
        self.events = {}
        self.missing = set()
        try:
            import vlc
            self.instance = vlc.Instance("--no-video")
            if self.instance is None:
                raise RuntimeError("libVLC could not initialize")
        except (ImportError, OSError, RuntimeError) as exc:
            LOG.error("Audio unavailable: %s; install python-vlc and libVLC", exc)

    def play(self, cue):
        if self.instance is None:
            return
        path = self.directory / f"{cue}.mp3"
        if not path.is_file():
            if cue not in self.missing:
                LOG.error("Audio file missing: %s", path)
                self.missing.add(cue)
            return
        self.missing.discard(cue)
        player = self.players.get(cue)
        if player is None:
            player = self.instance.media_player_new()
            if player is None:
                LOG.error("Could not create audio player for %s", path)
                return
            import vlc
            events = player.event_manager()
            if events.event_attach(vlc.EventType.MediaPlayerEncounteredError,
                                   self._playback_error, cue) != 0:
                LOG.error("Could not monitor audio playback errors for %s", path)
            self.events[cue] = events
            self.players[cue] = player
        media = self.instance.media_new(str(path.resolve()))
        if media is None:
            LOG.error("Could not open audio file %s", path)
            return
        player.set_media(media)
        media.release()
        if player.play() == -1:
            LOG.error("Could not play audio file %s", path)

    def _playback_error(self, _event, cue):
        LOG.error("Audio playback failed for %s", self.directory / f"{cue}.mp3")

    def close(self):
        for player in self.players.values():
            player.stop()
            player.release()
        if self.instance is not None:
            self.instance.release()
