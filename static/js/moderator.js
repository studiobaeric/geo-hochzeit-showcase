const currentPhotoImage = document.getElementById('currentPhotoImage');
const currentPhotoFallback = document.getElementById('currentPhotoFallback');

async function loadCurrentPhoto() {
    try {
        const response = await fetch('/static/data/photos.json');
        const photos = await response.json();
        const currentPhoto = photos[0];

        if (!currentPhoto) return;

        currentPhotoImage.src = `/static/photos/${currentPhoto.filename}`;
        currentPhotoImage.classList.add('is-loaded');
        currentPhotoFallback.classList.add('is-hidden');
    } catch (error) {
        console.error('Moderator photo could not be loaded:', error);
    }
}

loadCurrentPhoto();
