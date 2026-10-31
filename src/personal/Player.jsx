import { useEffect, useRef, useState, useMemo } from 'react';
import {
  X, Play, Pause, RotateCcw, RotateCw, Volume2, VolumeX,
  Maximize, Minimize, Settings, SkipForward, Loader2, Check
} from 'lucide-react';

function formatTime(s) {
  if (!s || !Number.isFinite(s) || s < 0) return '00:00';
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = Math.floor(s % 60);
  const pad = n => String(n).padStart(2, '0');
  if (hrs > 0) return `${hrs}:${pad(mins)}:${pad(secs)}`;
  return `${pad(mins)}:${pad(secs)}`;
}

export default function Player({
  source,
  title,
  subtitle = '',
  onClose,
  onProgress,
  resume = 0,
  subtitles = [],
  format = '',
  onFallback,
  onNextEpisode,
  hasNextEpisode = false
}) {
  const containerRef = useRef(null);
  const videoRef = useRef(null);
  const engineRef = useRef(null);
  const progressCallback = useRef(onProgress);
  progressCallback.current = onProgress;
  const fallbackRef = useRef(onFallback);
  fallbackRef.current = onFallback;
  const triggerFallbackRef = useRef(null);
  const hideControlsTimer = useRef(null);
  const lastTapRef = useRef({ time: 0, x: 0 });

  // Playback state
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [bufferedPercent, setBufferedPercent] = useState(0);
  const [isBuffering, setIsBuffering] = useState(true);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [error, setError] = useState('');
  const [doubleTapNotice, setDoubleTapNotice] = useState(null);

  // Tracks & controls UI
  const [audioTracks, setAudioTracks] = useState([]);
  const [currentAudio, setCurrentAudio] = useState(0);
  const [currentSubtitle, setCurrentSubtitle] = useState('off');
  const [controlsVisible, setControlsVisible] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState('main'); // 'main' | 'speed' | 'subtitles' | 'audio'
  const fallbackTriggered = useRef(false);

  // Show controls and reset hide timer
  const showControlsTemporarily = () => {
    setControlsVisible(true);
    if (hideControlsTimer.current) clearTimeout(hideControlsTimer.current);
    hideControlsTimer.current = setTimeout(() => {
      if (videoRef.current && !videoRef.current.paused && !showSettings) {
        setControlsVisible(false);
      }
    }, 3200);
  };

  const handleUserActivity = () => {
    showControlsTemporarily();
  };

  // Setup stream & engines
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let engine;
    let lastProgressTime = 0;
    let disposed = false;

    setError('');
    setIsBuffering(true);
    fallbackTriggered.current = false;

    const triggerFallback = (reason) => {
      if (!fallbackTriggered.current && fallbackRef.current) {
        fallbackTriggered.current = true;
        setError(reason || 'Source unavailable. Trying alternative source…');
        fallbackRef.current(video?.currentTime || resume).then(handled => {
          if (!handled && !disposed) {
            setError('This source could not be played. Reopen the title or choose a different source.');
          }
        }).catch(() => {
          if (!disposed) setError('This source could not be played. Reopen the title or choose a different source.');
        });
      } else if (!fallbackTriggered.current) {
        setError('This source could not be played. Reopen the title or choose a different source.');
      }
    };
    triggerFallbackRef.current = triggerFallback;

    (async () => {
      if (/hls|m3u8/i.test(format) || /\.m3u8(?:\?|$)/i.test(source)) {
        const { default: Hls } = await import('hls.js');
        if (disposed) return;
        if (Hls.isSupported()) {
          engine = new Hls({ enableWorker: true, lowLatencyMode: false });
          engine.loadSource(source);
          engine.attachMedia(video);
          engine.on(Hls.Events.ERROR, (_, data) => {
            if (data.fatal) {
              if (data.type === Hls.ErrorTypes.NETWORK_ERROR && fallbackRef.current) {
                triggerFallback('HLS network error. Switching to alternative source…');
              } else {
                setError('Playback failed. Reopen the title to refresh its source.');
              }
            }
          });
          engine.on(Hls.Events.AUDIO_TRACKS_UPDATED, (_, data) => {
            const tracks = data.audioTracks.map((t, idx) => ({
              index: idx,
              label: t.name || t.lang || `Audio ${idx + 1}`
            }));
            setAudioTracks(tracks);
          });
        } else {
          video.src = source;
        }
      } else if (/dash|mpd/i.test(format) || /\.mpd(?:\?|$)/i.test(source)) {
        const { default: dashjs } = await import('dashjs');
        if (disposed) return;
        engine = dashjs.MediaPlayer().create();
        engine.initialize(video, source, false);
        engine.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, () => {
          const tracks = engine.getTracksFor('audio').map((t, idx) => ({
            index: idx,
            label: t.lang || `Audio ${idx + 1}`
          }));
          setAudioTracks(tracks);
        });
        engine.on(dashjs.MediaPlayer.events.ERROR, () => {
          triggerFallback('DASH source could not be played. Switching to alternative HLS source…');
        });
      } else {
        video.src = source;
      }
      engineRef.current = engine;
    })().catch(() => triggerFallback('Could not load stream engine. Trying alternative source…'));

    // Video event listeners
    const onLoadedMetadata = () => {
      setDuration(video.duration || 0);
      if (resume > 0 && resume < video.duration - 10) {
        video.currentTime = resume;
      }
      video.play().catch(() => setIsPlaying(false));
    };

    const onTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      // Progress calculation
      if (Date.now() - lastProgressTime > 8000 && video.duration) {
        lastProgressTime = Date.now();
        progressCallback.current?.(video.currentTime, video.duration);
      }
      // Calculate buffer percent
      if (video.buffered && video.buffered.length > 0 && video.duration) {
        const bufferedEnd = video.buffered.end(video.buffered.length - 1);
        setBufferedPercent(Math.min(100, (bufferedEnd / video.duration) * 100));
      }
    };

    const onPlay = () => setIsPlaying(true);
    const onPause = () => {
      setIsPlaying(false);
      setControlsVisible(true);
    };
    const onWaiting = () => setIsBuffering(true);
    const onPlaying = () => setIsBuffering(false);
    const onCanPlay = () => setIsBuffering(false);
    const onSeeking = () => setIsBuffering(true);
    const onSeeked = () => setIsBuffering(false);
    const onEnded = () => {
      setIsPlaying(false);
      setControlsVisible(true);
      if (hasNextEpisode && onNextEpisode) {
        onNextEpisode();
      }
    };

    video.addEventListener('loadedmetadata', onLoadedMetadata);
    video.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('waiting', onWaiting);
    video.addEventListener('playing', onPlaying);
    video.addEventListener('canplay', onCanPlay);
    video.addEventListener('seeking', onSeeking);
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('ended', onEnded);

    showControlsTemporarily();

    return () => {
      disposed = true;
      progressCallback.current?.(video.currentTime, video.duration);
      video.removeEventListener('loadedmetadata', onLoadedMetadata);
      video.removeEventListener('timeupdate', onTimeUpdate);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('waiting', onWaiting);
      video.removeEventListener('playing', onPlaying);
      video.removeEventListener('canplay', onCanPlay);
      video.removeEventListener('seeking', onSeeking);
      video.removeEventListener('seeked', onSeeked);
      video.removeEventListener('ended', onEnded);

      if (hideControlsTimer.current) clearTimeout(hideControlsTimer.current);
      if (engine?.destroy) engine.destroy();
      else engine?.reset?.();
      engineRef.current = null;
      video.removeAttribute('src');
      video.load();
    };
  }, [source, resume, format]);

  // Controls actions
  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play().then(() => setIsPlaying(true)).catch(() => {});
    } else {
      video.pause();
      setIsPlaying(false);
    }
    showControlsTemporarily();
  };

  const skip = (delta) => {
    const video = videoRef.current;
    if (!video) return;
    const target = Math.max(0, Math.min(video.duration || 0, video.currentTime + delta));
    video.currentTime = target;
    setCurrentTime(target);
    showControlsTemporarily();
  };

  const handleSeek = (e) => {
    const video = videoRef.current;
    if (!video || !duration) return;
    const newTime = (Number(e.target.value) / 100) * duration;
    video.currentTime = newTime;
    setCurrentTime(newTime);
    showControlsTemporarily();
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (!video) return;
    const nextMuted = !video.muted;
    video.muted = nextMuted;
    setIsMuted(nextMuted);
    showControlsTemporarily();
  };

  const handleVolumeChange = (e) => {
    const video = videoRef.current;
    if (!video) return;
    const val = Number(e.target.value);
    video.volume = val;
    video.muted = val === 0;
    setVolume(val);
    setIsMuted(val === 0);
    showControlsTemporarily();
  };

  const toggleFullscreen = () => {
    const container = containerRef.current;
    if (!container) return;
    if (!document.fullscreenElement) {
      if (container.requestFullscreen) container.requestFullscreen();
      else if (container.webkitRequestFullscreen) container.webkitRequestFullscreen();
    } else {
      if (document.exitFullscreen) document.exitFullscreen();
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
    }
  };

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFsChange);
    document.addEventListener('webkitfullscreenchange', onFsChange);
    return () => {
      document.removeEventListener('fullscreenchange', onFsChange);
      document.removeEventListener('webkitfullscreenchange', onFsChange);
    };
  }, []);

  // Keyboard Shortcuts
  useEffect(() => {
    const onKeyDown = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      const v = videoRef.current;
      if (!v) return;

      switch (e.key.toLowerCase()) {
        case ' ':
        case 'k':
          e.preventDefault();
          togglePlay();
          break;
        case 'arrowleft':
        case 'j':
          e.preventDefault();
          skip(-10);
          break;
        case 'arrowright':
        case 'l':
          e.preventDefault();
          skip(10);
          break;
        case 'arrowup':
          e.preventDefault();
          setVolume(prev => {
            const next = Math.min(1, Number((prev + 0.1).toFixed(2)));
            v.volume = next;
            v.muted = false;
            setIsMuted(false);
            return next;
          });
          showControlsTemporarily();
          break;
        case 'arrowdown':
          e.preventDefault();
          setVolume(prev => {
            const next = Math.max(0, Number((prev - 0.1).toFixed(2)));
            v.volume = next;
            return next;
          });
          showControlsTemporarily();
          break;
        case 'm':
          e.preventDefault();
          toggleMute();
          break;
        case 'f':
          e.preventDefault();
          toggleFullscreen();
          break;
        case 'escape':
          if (showSettings) {
            setShowSettings(false);
          } else if (document.fullscreenElement) {
            document.exitFullscreen().catch(() => {});
          } else {
            onClose();
          }
          break;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showSettings]);

  // Mobile Double Tap
  const handleTouchStart = (e) => {
    const now = Date.now();
    const touch = e.changedTouches[0];
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = touch.clientX - rect.left;
    const isLeft = x < rect.width / 2;

    if (now - lastTapRef.current.time < 300 && Math.abs(x - lastTapRef.current.x) < 70) {
      if (isLeft) {
        skip(-10);
        setDoubleTapNotice({ side: 'left', text: '-10s' });
      } else {
        skip(10);
        setDoubleTapNotice({ side: 'right', text: '+10s' });
      }
      setTimeout(() => setDoubleTapNotice(null), 850);
      lastTapRef.current = { time: 0, x: 0 };
    } else {
      lastTapRef.current = { time: now, x };
      handleUserActivity();
    }
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;
  const isNearEnd = duration > 60 && duration - currentTime <= 25;

  return (
    <div
      ref={containerRef}
      className={`player-screen cinematic ${controlsVisible ? 'controls-active' : 'controls-hidden'}`}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseMove={handleUserActivity}
      onTouchStart={handleTouchStart}
    >
      {/* Background Video */}
      <video
        ref={videoRef}
        playsInline
        crossOrigin="use-credentials"
        onClick={togglePlay}
        onError={() => triggerFallbackRef.current?.('Video decoding error. Trying alternative source…')}
      >
        {subtitles.map(track => (
          <track key={track.url} kind="subtitles" label={track.label} src={track.url} srcLang="und" />
        ))}
      </video>

      {/* Buffering Indicator */}
      {isBuffering && (
        <div className="player-buffering">
          <Loader2 className="spinner" size={54} />
        </div>
      )}

      {/* Double Tap Ripple Notice */}
      {doubleTapNotice && (
        <div className={`double-tap-feedback ${doubleTapNotice.side}`}>
          <div className="ripple-badge">
            {doubleTapNotice.side === 'left' ? <RotateCcw size={28} /> : <RotateCw size={28} />}
            <span>{doubleTapNotice.text}</span>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="player-error-banner">
          <p>{error}</p>
        </div>
      )}

      {/* Next Episode Floating Card Near End of Episode */}
      {isNearEnd && hasNextEpisode && onNextEpisode && (
        <div className="next-ep-prompt">
          <span>Up Next</span>
          <button className="primary" onClick={onNextEpisode}>
            <SkipForward size={16} fill="currentColor" /> Play Next Episode
          </button>
        </div>
      )}

      {/* Top Header Controls Overlay */}
      <div className="player-overlay top-overlay">
        <div className="title-group">
          <span className="now-playing-label">NOW PLAYING</span>
          <h2>{title}</h2>
          {subtitle && <small className="subtitle-label">{subtitle}</small>}
        </div>
        <div className="top-right-actions">
          {hasNextEpisode && onNextEpisode && (
            <button className="glass-btn next-ep-btn" onClick={onNextEpisode} title="Next Episode">
              <SkipForward size={17} />
              <span>Next</span>
            </button>
          )}
          <button className="icon-button close-btn" onClick={onClose} aria-label="Close player">
            <X size={22} />
          </button>
        </div>
      </div>

      {/* Center Action Controls Overlay (Tap/Click to play/pause) */}
      <div className="player-overlay center-overlay" onClick={togglePlay}>
        <button
          className="center-ctrl-btn"
          onClick={e => { e.stopPropagation(); skip(-10); }}
          title="Rewind 10s"
          aria-label="Rewind 10 seconds"
        >
          <RotateCcw size={32} />
          <span>10</span>
        </button>
        <button
          className="center-play-btn"
          onClick={e => { e.stopPropagation(); togglePlay(); }}
          aria-label={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? <Pause size={42} fill="currentColor" /> : <Play size={42} fill="currentColor" />}
        </button>
        <button
          className="center-ctrl-btn"
          onClick={e => { e.stopPropagation(); skip(10); }}
          title="Forward 10s"
          aria-label="Forward 10 seconds"
        >
          <RotateCw size={32} />
          <span>10</span>
        </button>
      </div>

      {/* Bottom Controls Overlay */}
      <div className="player-overlay bottom-overlay">
        {/* Progress Scrubber */}
        <div className="scrubber-container">
          <div className="scrubber-track">
            <div className="buffer-bar" style={{ width: `${bufferedPercent}%` }} />
            <div className="progress-bar" style={{ width: `${progressPercent}%` }} />
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="0.1"
            value={progressPercent || 0}
            onChange={handleSeek}
            className="seek-slider"
            aria-label="Seek video"
          />
        </div>

        {/* Bottom Actions Bar */}
        <div className="bottom-bar">
          <div className="bottom-left">
            <button className="icon-btn" onClick={togglePlay} aria-label={isPlaying ? 'Pause' : 'Play'}>
              {isPlaying ? <Pause size={22} /> : <Play size={22} fill="currentColor" />}
            </button>
            <button className="icon-btn" onClick={() => skip(-10)} title="Rewind 10s">
              <RotateCcw size={20} />
            </button>
            <button className="icon-btn" onClick={() => skip(10)} title="Forward 10s">
              <RotateCw size={20} />
            </button>

            {/* Volume Control */}
            <div className="volume-wrapper">
              <button className="icon-btn" onClick={toggleMute} aria-label={isMuted ? 'Unmute' : 'Mute'}>
                {isMuted || volume === 0 ? <VolumeX size={21} /> : <Volume2 size={21} />}
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={isMuted ? 0 : volume}
                onChange={handleVolumeChange}
                className="volume-slider"
                aria-label="Volume slider"
              />
            </div>

            {/* Time Stamp */}
            <div className="time-display">
              <span>{formatTime(currentTime)}</span>
              <span className="divider">/</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>

          <div className="bottom-right">
            {/* Settings Trigger */}
            <div className="settings-wrapper">
              <button
                className={`icon-btn ${showSettings ? 'active' : ''}`}
                onClick={() => {
                  setShowSettings(!showSettings);
                  setSettingsTab('main');
                  showControlsTemporarily();
                }}
                title="Playback Settings"
                aria-label="Playback Settings"
              >
                <Settings size={21} />
              </button>

              {/* Glassmorphic Settings Popover */}
              {showSettings && (
                <div className="settings-popover" onClick={e => e.stopPropagation()}>
                  {settingsTab === 'main' && (
                    <div className="menu-list">
                      <button className="menu-item" onClick={() => setSettingsTab('speed')}>
                        <span>Speed</span>
                        <small>{playbackSpeed}×</small>
                      </button>
                      <button className="menu-item" onClick={() => setSettingsTab('subtitles')}>
                        <span>Subtitles</span>
                        <small>{currentSubtitle === 'off' ? 'Off' : subtitles[Number(currentSubtitle)]?.label || 'On'}</small>
                      </button>
                      {audioTracks.length > 1 && (
                        <button className="menu-item" onClick={() => setSettingsTab('audio')}>
                          <span>Audio Track</span>
                          <small>{audioTracks[currentAudio]?.label || 'Default'}</small>
                        </button>
                      )}
                    </div>
                  )}

                  {settingsTab === 'speed' && (
                    <div className="menu-list">
                      <div className="menu-header">
                        <button onClick={() => setSettingsTab('main')}>← Back</button>
                        <span>Playback Speed</span>
                      </div>
                      {[0.75, 1, 1.25, 1.5, 2].map(speed => (
                        <button
                          key={speed}
                          className={`menu-item ${playbackSpeed === speed ? 'selected' : ''}`}
                          onClick={() => {
                            if (videoRef.current) videoRef.current.playbackRate = speed;
                            setPlaybackSpeed(speed);
                            setShowSettings(false);
                          }}
                        >
                          <span>{speed}×</span>
                          {playbackSpeed === speed && <Check size={16} />}
                        </button>
                      ))}
                    </div>
                  )}

                  {settingsTab === 'subtitles' && (
                    <div className="menu-list">
                      <div className="menu-header">
                        <button onClick={() => setSettingsTab('main')}>← Back</button>
                        <span>Subtitles</span>
                      </div>
                      <button
                        className={`menu-item ${currentSubtitle === 'off' ? 'selected' : ''}`}
                        onClick={() => {
                          setCurrentSubtitle('off');
                          if (videoRef.current?.textTracks) {
                            Array.from(videoRef.current.textTracks).forEach(t => (t.mode = 'disabled'));
                          }
                          setShowSettings(false);
                        }}
                      >
                        <span>Off</span>
                        {currentSubtitle === 'off' && <Check size={16} />}
                      </button>
                      {subtitles.map((track, idx) => (
                        <button
                          key={track.url}
                          className={`menu-item ${currentSubtitle === String(idx) ? 'selected' : ''}`}
                          onClick={() => {
                            setCurrentSubtitle(String(idx));
                            if (videoRef.current?.textTracks) {
                              Array.from(videoRef.current.textTracks).forEach((t, i) => {
                                t.mode = i === idx ? 'showing' : 'disabled';
                              });
                            }
                            setShowSettings(false);
                          }}
                        >
                          <span>{track.label}</span>
                          {currentSubtitle === String(idx) && <Check size={16} />}
                        </button>
                      ))}
                    </div>
                  )}

                  {settingsTab === 'audio' && (
                    <div className="menu-list">
                      <div className="menu-header">
                        <button onClick={() => setSettingsTab('main')}>← Back</button>
                        <span>Audio Tracks</span>
                      </div>
                      {audioTracks.map((track, idx) => (
                        <button
                          key={track.index}
                          className={`menu-item ${currentAudio === idx ? 'selected' : ''}`}
                          onClick={() => {
                            setCurrentAudio(idx);
                            const engine = engineRef.current;
                            if (engine) {
                              if ('audioTrack' in engine) engine.audioTrack = track.index;
                              else engine.setCurrentTrack?.(engine.getTracksFor('audio')[track.index]);
                            }
                            setShowSettings(false);
                          }}
                        >
                          <span>{track.label}</span>
                          {currentAudio === idx && <Check size={16} />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Fullscreen Toggle */}
            <button
              className="icon-btn"
              onClick={toggleFullscreen}
              title={isFullscreen ? 'Exit Fullscreen (f)' : 'Fullscreen (f)'}
              aria-label="Toggle Fullscreen"
            >
              {isFullscreen ? <Minimize size={21} /> : <Maximize size={21} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
