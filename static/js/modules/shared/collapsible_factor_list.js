(function() {
    function bindCollapsibleFactorLists(root) {
        const scope = root || document;
        scope.querySelectorAll('.collapsible-factor-header').forEach(header => {
            if (header.dataset.bound === '1') return;
            header.dataset.bound = '1';
            header.addEventListener('click', function(event) {
                event.preventDefault();
                const node = header.closest('.collapsible-factor-node');
                if (node) node.classList.toggle('open');
            });
        });
    }

    window.bindCollapsibleFactorLists = bindCollapsibleFactorLists;
    document.addEventListener('DOMContentLoaded', function() {
        bindCollapsibleFactorLists(document);
    });
})();
