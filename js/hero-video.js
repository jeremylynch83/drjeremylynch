(function () {
  'use strict';

  var video = document.querySelector('.hero__video');
  if (!video) return;

  var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var sources = Array.prototype.map.call(video.querySelectorAll('source'), function (source) {
    return { src: source.getAttribute('data-src'), type: source.type };
  }).filter(function (source) {
    return source.src && video.canPlayType(source.type);
  });
  var index = -1;
  var timer;
  var stallTimer;
  var generation = 0;
  var blocked = false;
  var exhausted = false;

  function still() {
    video.classList.remove('is-playing');
  }

  function clearTimer() {
    window.clearTimeout(timer);
    window.clearTimeout(stallTimer);
  }

  function attemptPlay() {
    if (motion.matches || blocked || document.hidden || index < 0) return;
    var request = generation;
    var result = video.play();
    if (result && result.catch) result.catch(function (error) {
      if (request !== generation) return;
      if (error.name === 'NotAllowedError') {
        blocked = true;
        clearTimer();
        still();
      }
      // Loading a replacement source or leaving the page may abort a play request.
      // Decode/network errors are handled by the media error event and timeout.
    });
  }

  function nextSource() {
    if (motion.matches || blocked || document.hidden) return;
    clearTimer();
    still();
    generation += 1;
    index += 1;
    if (index >= sources.length) {
      exhausted = true;
      video.pause();
      video.removeAttribute('src');
      video.load();
      return;
    }
    exhausted = false;
    video.muted = true;
    video.src = sources[index].src;
    video.load();
    timer = window.setTimeout(nextSource, 12000);
    attemptPlay();
  }

  video.addEventListener('playing', function () {
    clearTimer();
    if (motion.matches || document.hidden) {
      video.pause();
      return;
    }
    video.classList.add('is-playing');
  });
  video.addEventListener('waiting', function () {
    window.clearTimeout(stallTimer);
    // Keep downloading, but show the first frame during a prolonged buffer pause.
    stallTimer = window.setTimeout(still, 3000);
  });
  video.addEventListener('error', function () {
    if (!exhausted) nextSource();
  });
  video.addEventListener('pause', still);

  function applyMotionPreference() {
    if (motion.matches) {
      generation += 1;
      clearTimer();
      still();
      video.pause();
      video.removeAttribute('src');
      video.load();
      index = -1;
    } else if (index < 0) {
      nextSource();
    }
  }
  if (motion.addEventListener) motion.addEventListener('change', applyMotionPreference);
  else motion.addListener(applyMotionPreference);

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      clearTimer();
      video.pause();
    } else if (index < 0) {
      nextSource();
    } else if (!exhausted) {
      if (!video.classList.contains('is-playing') && !blocked) {
        timer = window.setTimeout(nextSource, 12000);
      }
      attemptPlay();
    }
  });
  window.addEventListener('online', function () {
    if (!motion.matches && !blocked && exhausted) {
      index = -1;
      nextSource();
    }
  });

  applyMotionPreference();
})();
