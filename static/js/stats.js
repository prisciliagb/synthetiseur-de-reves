/**
 * Graphiques de la page « Statistiques » (Chart.js).
 *
 * Les données sont calculées par Django (dashboard/services.py) et placées
 * dans la page par la balise {{ chart_data|json_script:"stats-data" }}.
 */
(function () {
  "use strict";

  const dataElement = document.getElementById("stats-data");
  if (!dataElement || !window.Chart) {
    return;
  }
  const data = JSON.parse(dataElement.textContent);

  // Couleurs du thème (static/css/theme.css) : l'émotion dominante en violet,
  // le reste en gris clair.
  const COLORS = {
    main: "#5b34c7",
    muted: "#d6d1e6",
    grid: "#ece8f6",
    text: "#5d5680",
  };

  Chart.defaults.color = COLORS.text;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

  // Réglages communs : barres fines aux bouts arrondis, grille discrète,
  // pas de légende (une seule série : le titre de la carte suffit).
  const barStyle = { borderRadius: 4, borderSkipped: "start", maxBarThickness: 32 };
  const countAxis = {
    beginAtZero: true,
    ticks: { precision: 0 },
    grid: { color: COLORS.grid },
    border: { display: false },
  };
  const categoryAxis = { grid: { display: false } };

  function plural(count) {
    return count + " rêve" + (count > 1 ? "s" : "");
  }

  // --- Rêves par semaine ---------------------------------------------------
  new Chart(document.getElementById("chart-weeks"), {
    type: "bar",
    data: {
      labels: data.weeks.labels,
      datasets: [{ data: data.weeks.counts, backgroundColor: COLORS.main, ...barStyle }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => "Semaine du " + items[0].label,
            label: (item) => plural(item.parsed.y),
          },
        },
      },
      scales: { x: categoryAxis, y: countAxis },
    },
  });

  // --- Répartition des émotions (barres horizontales, de la plus fréquente) --
  new Chart(document.getElementById("chart-emotions"), {
    type: "bar",
    data: {
      labels: data.emotions.labels,
      datasets: [{
        data: data.emotions.counts,
        backgroundColor: data.emotions.dominant.map((isDominant) => (
          isDominant ? COLORS.main : COLORS.muted
        )),
        ...barStyle,
      }],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (item) => plural(item.parsed.x) } },
      },
      scales: { x: countAxis, y: categoryAxis },
    },
  });
})();
