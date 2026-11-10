/**
 * Enregistrement d'un rêve au micro.
 *
 * 1. « Démarrer » demande l'accès au micro puis lance l'enregistrement.
 * 2. Le chronomètre s'affiche ; l'enregistrement s'arrête seul à la durée maximale.
 * 3. « Arrêter » termine l'enregistrement et affiche un lecteur pour le réécouter.
 * 4. « Envoyer » transmet l'audio au serveur Django.
 */
(function () {
  "use strict";

  // --- Éléments de la page -------------------------------------------------
  const recorderBox = document.getElementById("recorder");
  const startButton = document.getElementById("btn-start");
  const stopButton = document.getElementById("btn-stop");
  const sendButton = document.getElementById("btn-send");
  const timerDisplay = document.getElementById("recorder-timer");
  const reviewBox = document.getElementById("recorder-review");
  const player = document.getElementById("recorder-player");
  const errorBox = document.getElementById("recorder-error");
  const infoBox = document.getElementById("recorder-info");

  // --- Réglages transmis par Django (attributs data-*) ---------------------
  const uploadUrl = recorderBox.dataset.uploadUrl;
  const maxSeconds = Number(recorderBox.dataset.maxSeconds);
  const maxSize = Number(recorderBox.dataset.maxSize);
  const csrfToken = recorderBox.querySelector("[name=csrfmiddlewaretoken]").value;

  // Formats essayés dans l'ordre : WebM (Chrome, Firefox), Ogg, puis MP4 (Safari).
  const PREFERRED_TYPES = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];

  // --- État de l'enregistrement --------------------------------------------
  let mediaRecorder = null;
  let chunks = [];
  let recording = null; // l'audio terminé (Blob)
  let startedAt = 0;
  let timerId = null;

  // --- Messages ---------------------------------------------------------------
  function showError(message) {
    infoBox.classList.add("d-none");
    errorBox.textContent = message;
    errorBox.classList.remove("d-none");
  }

  function showInfo(message) {
    errorBox.classList.add("d-none");
    infoBox.textContent = message;
    infoBox.classList.remove("d-none");
  }

  function hideMessages() {
    errorBox.classList.add("d-none");
    infoBox.classList.add("d-none");
  }

  /** Traduit une erreur du micro en message compréhensible. */
  function microphoneErrorMessage(error) {
    switch (error.name) {
      case "NotAllowedError":
      case "SecurityError":
        return "Vous avez refusé l'accès au micro. Autorisez-le dans les réglages "
          + "du navigateur (icône à gauche de l'adresse), puis réessayez.";
      case "NotFoundError":
      case "OverconstrainedError":
        return "Aucun micro n'a été détecté. Branchez un micro puis réessayez.";
      case "NotReadableError":
        return "Le micro est déjà utilisé par une autre application. "
          + "Fermez-la puis réessayez.";
      default:
        return "Impossible d'accéder au micro. Réessayez ou changez de navigateur.";
    }
  }

  // --- Chronomètre -------------------------------------------------------------
  function formatTime(totalSeconds) {
    const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    return minutes + ":" + seconds;
  }

  function updateTimer() {
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    timerDisplay.textContent = formatTime(Math.min(elapsed, maxSeconds));
    if (elapsed >= maxSeconds) {
      stopRecording();
      showInfo("Durée maximale atteinte : l'enregistrement s'est arrêté "
        + "automatiquement. Vous pouvez le réécouter puis l'envoyer.");
    }
  }

  // --- Enregistrement ------------------------------------------------------------
  async function startRecording() {
    hideMessages();

    let stream;
    try {
      // Le navigateur affiche ici la demande d'autorisation du micro.
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      showError(microphoneErrorMessage(error));
      return;
    }

    // Un nouvel enregistrement remplace le précédent.
    if (player.src) {
      URL.revokeObjectURL(player.src);
      player.removeAttribute("src");
    }
    reviewBox.classList.add("d-none");
    recording = null;
    chunks = [];

    const mimeType = PREFERRED_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
    mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    });
    mediaRecorder.addEventListener("stop", () => {
      // Libère le micro : le voyant d'enregistrement du navigateur s'éteint.
      stream.getTracks().forEach((track) => track.stop());
      recording = new Blob(chunks, { type: mediaRecorder.mimeType });
      player.src = URL.createObjectURL(recording);
      reviewBox.classList.remove("d-none");
      sendButton.disabled = false;
    });
    mediaRecorder.start();

    startedAt = Date.now();
    timerDisplay.textContent = formatTime(0);
    timerId = setInterval(updateTimer, 250);
    startButton.disabled = true;
    stopButton.disabled = false;
  }

  function stopRecording() {
    clearInterval(timerId);
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    startButton.disabled = false;
    startButton.textContent = "● Recommencer";
    stopButton.disabled = true;
  }

  // --- Envoi au serveur -----------------------------------------------------------
  function fileExtension(type) {
    if (type.includes("ogg")) return "ogg";
    if (type.includes("mp4")) return "mp4";
    return "webm";
  }

  async function sendRecording() {
    if (!recording) {
      return;
    }
    if (recording.size > maxSize) {
      showError("L'enregistrement est trop lourd. Faites un enregistrement plus court.");
      return;
    }

    const formData = new FormData();
    formData.append("audio", recording, "reve." + fileExtension(recording.type));

    sendButton.disabled = true;
    startButton.disabled = true;
    sendButton.textContent = "Envoi en cours…";
    hideMessages();

    try {
      const response = await fetch(uploadUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        body: formData,
      });
      const data = await response.json();
      if (response.ok) {
        showInfo(data.message);
        recording = null;
        reviewBox.classList.add("d-none");
        timerDisplay.textContent = formatTime(0);
        startButton.textContent = "● Raconter un autre rêve";
      } else {
        showError(data.error || "L'envoi a échoué. Réessayez.");
        sendButton.disabled = false;
      }
    } catch (error) {
      showError("Impossible de joindre le serveur. Vérifiez votre connexion puis réessayez.");
      sendButton.disabled = false;
    } finally {
      sendButton.textContent = "Envoyer mon rêve";
      startButton.disabled = false;
    }
  }

  // --- Démarrage de la page ------------------------------------------------------------
  // navigator.mediaDevices n'existe que sur une page sécurisée (https ou localhost).
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    showError("Votre navigateur ne permet pas l'enregistrement audio. "
      + "Utilisez une version récente de Chrome, Firefox, Edge ou Safari.");
    startButton.disabled = true;
    return;
  }

  startButton.addEventListener("click", startRecording);
  stopButton.addEventListener("click", stopRecording);
  sendButton.addEventListener("click", sendRecording);
})();
