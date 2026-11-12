/**
 * Enchaînement des étapes de traitement d'un rêve.
 *
 * Après la transcription, le serveur indique la prochaine étape et son adresse
 * (`next_step`, `next_url`). On la lance, puis on recommence avec la réponse,
 * jusqu'à ce qu'il n'y ait plus d'étape : on ouvre alors la page du rêve.
 *
 * L'indicateur (templates/dreams/_progress.html) montre l'étape en cours.
 * Utilisé par la page d'enregistrement (recorder.js) et par le bouton
 * « Relancer » de la page d'un rêve.
 */
window.DreamPipeline = (function () {
  "use strict";

  const STEPS = ["transcription", "analysis", "image"];
  // Garde-fou : jamais plus de requêtes que d'étapes, même si le serveur se trompe.
  const MAX_REQUESTS = STEPS.length;

  const ICONS = {
    pending: '<span class="text-muted">○</span>',
    current: '<span class="spinner-border spinner-border-sm text-primary" role="status"></span>',
    done: "✅",
    failed: "❌",
  };

  /** Affiche l'état d'une étape : pending, current, done ou failed. */
  function setStep(box, step, state) {
    const item = box.querySelector('[data-step="' + step + '"]');
    item.querySelector(".step-icon").innerHTML = ICONS[state];
    item.classList.toggle("fw-bold", state === "current");
    item.classList.toggle("text-muted", state === "pending");
  }

  /** Affiche l'indicateur : les étapes avant `currentStep` sont faites. */
  function show(box, currentStep) {
    const index = STEPS.indexOf(currentStep);
    STEPS.forEach((step, i) => {
      if (i < index) setStep(box, step, "done");
      else if (i === index) setStep(box, step, "current");
      else setStep(box, step, "pending");
    });
    box.classList.remove("d-none");
  }

  /**
   * Envoie une requête POST et lit la réponse JSON.
   * Ne lève jamais d'erreur : un problème réseau donne { ok: false }.
   */
  async function post(url, csrfToken, body) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        body: body,
      });
      const data = await response.json();
      return { ok: response.ok && data.ok, data: data };
    } catch (error) {
      return {
        ok: false,
        data: { error: "Impossible de joindre le serveur. Vérifiez votre connexion puis réessayez." },
      };
    }
  }

  /**
   * Lance les étapes restantes l'une après l'autre.
   *
   * @param {Object} state Réponse du serveur : next_step, next_url, redirect_url.
   * @param {Object} options box (indicateur), csrfToken, onError(message, state).
   */
  async function continueFrom(state, options) {
    let requests = 0;
    while (state.next_url && requests < MAX_REQUESTS) {
      requests += 1;
      show(options.box, state.next_step);
      const result = await post(state.next_url, options.csrfToken);
      if (!result.ok) {
        setStep(options.box, state.next_step, "failed");
        options.onError(
          result.data.error || "Une erreur inattendue est survenue.",
          result.data.redirect_url || state.redirect_url,
        );
        return;
      }
      state = result.data;
    }
    STEPS.forEach((step) => setStep(options.box, step, "done"));
    window.location.href = state.redirect_url;
  }

  // --- Page d'un rêve : bouton « Relancer les étapes manquantes » ------------
  const resumeBox = document.getElementById("pipeline-resume");
  if (resumeBox) {
    const button = document.getElementById("btn-resume");
    const errorBox = document.getElementById("pipeline-error");
    button.addEventListener("click", () => {
      button.disabled = true;
      errorBox.classList.add("d-none");
      continueFrom(
        {
          next_step: resumeBox.dataset.nextStep,
          next_url: resumeBox.dataset.nextUrl,
          redirect_url: resumeBox.dataset.redirectUrl,
        },
        {
          box: document.getElementById("pipeline-progress"),
          csrfToken: resumeBox.querySelector("[name=csrfmiddlewaretoken]").value,
          onError: (message) => {
            errorBox.textContent = message;
            errorBox.classList.remove("d-none");
            button.disabled = false;
          },
        },
      );
    });
  }

  return { show: show, setStep: setStep, post: post, continueFrom: continueFrom };
})();
