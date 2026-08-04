const year = document.querySelector("[data-year]");
if (year) year.textContent = new Date().getFullYear();

const shareButton = document.querySelector("[data-share-show]");
if (shareButton) {
  const status = document.querySelector("[data-share-status]");
  shareButton.addEventListener("click", async () => {
    const shareData = {
      title: shareButton.dataset.shareTitle,
      text: shareButton.dataset.shareText,
      url: `${window.location.origin}/music#upcoming`,
    };

    try {
      if (navigator.share) {
        await navigator.share(shareData);
        if (status) status.textContent = "Shared.";
      } else {
        await navigator.clipboard.writeText(shareData.url);
        if (status) status.textContent = "Show link copied.";
      }
    } catch (error) {
      if (error.name !== "AbortError" && status) status.textContent = "Copy the page URL to share.";
    }
  });
}
