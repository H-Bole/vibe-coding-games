const controls = document.querySelector('#search-tools');
const search = document.querySelector('#game-search');
const filters = [...controls.querySelectorAll('[data-filter]')];
const resultCount = document.querySelector('#result-count');
const emptyResults = document.querySelector('#empty-results');

const normalize = (text) => text.normalize('NFKC').toLowerCase();
const games = [...document.querySelectorAll('.game-card')].map((card) => ({
  card,
  group: card.dataset.group,
  names: normalize(`${card.dataset.name} ${card.dataset.aliases}`),
}));

let activeGroup = 'all';

function updateResults() {
  const words = normalize(search.value).trim().split(/\s+/);
  let matches = 0;
  for (const game of games) {
    const groupMatches = activeGroup === 'all' || game.group === activeGroup;
    const nameMatches = words.every((word) => game.names.includes(word));
    game.card.hidden = !groupMatches || !nameMatches;
    if (!game.card.hidden) matches += 1;
  }
  resultCount.textContent = matches === games.length ? `共 ${matches} 款` : `找到 ${matches} 款`;
  emptyResults.hidden = matches !== 0;
}

search.addEventListener('input', updateResults);
for (const filter of filters) {
  filter.addEventListener('click', () => {
    activeGroup = filter.dataset.filter;
    for (const button of filters) {
      button.setAttribute('aria-pressed', String(button === filter));
    }
    updateResults();
  });
}

controls.hidden = false;
updateResults();
