"""Market-data recorder and leaderboard snapshots (F4).

Recorded streams go through ``store.RecordingStore`` (compressed, day-partitioned, hashed); the loop is
``service.Recorder``; the sources it reads are the Protocols of ``ports``.
"""
