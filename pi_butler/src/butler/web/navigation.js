(() => {
  const navigation = document.getElementById('butler-navigation');
  const toggle = document.getElementById('butler-navigation-toggle');
  function close() {
    toggle.setAttribute('aria-expanded', 'false');
  }
  toggle.addEventListener('click', () => {
    toggle.setAttribute('aria-expanded', String(toggle.getAttribute('aria-expanded') !== 'true'));
  });
  document.addEventListener('click', (event) => {
    if (!navigation.contains(event.target) || event.target.closest('a')) close();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
      close();
      toggle.focus();
    }
  });
})();
