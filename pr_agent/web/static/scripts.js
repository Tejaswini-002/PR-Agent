document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.pr-list .pr-item .summary-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const prNumber = btn.closest('.pr-item').querySelector('strong').textContent.replace('#', '').trim();
      // Redirect to summary form for this PR
      const form = document.getElementById('summarize-form');
      if (form) {
        form.querySelector('input[name="pr_detail"]').value = prNumber;
        form.submit();
      }
    });
  });
});
