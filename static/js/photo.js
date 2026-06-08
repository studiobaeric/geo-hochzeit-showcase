// Zoom-Funktionalität für Fotos
export class PhotoZoom {
    constructor(imageId, containerId, resetButtonId) {
        this.photoImage = document.getElementById(imageId);
        this.photoContainer = document.getElementById(containerId);
        this.resetZoomButton = document.getElementById(resetButtonId);

        this.scale = 1;
        this.isPanning = false;
        this.startX = 0;
        this.startY = 0;
        this.translateX = 0;
        this.translateY = 0;
        this.initialDistance = 0;
        this.touchStartX = 0;
        this.touchStartY = 0;

        this.initEventListeners();
    }

    getBounds() {
        const containerRect = this.photoContainer.getBoundingClientRect();
        const imageRect = this.photoImage.getBoundingClientRect();

        // Berechne maximale Verschiebung
        const maxX = Math.max(0, (imageRect.width - containerRect.width) / 2);
        const maxY = Math.max(0, (imageRect.height - containerRect.height) / 2);

        return { maxX, maxY };
    }

    clampTranslate() {
        const bounds = this.getBounds();
        this.translateX = Math.max(-bounds.maxX, Math.min(bounds.maxX, this.translateX));
        this.translateY = Math.max(-bounds.maxY, Math.min(bounds.maxY, this.translateY));
    }

    updateImageTransform() {
        this.clampTranslate();
        this.photoImage.style.transform = `translate(${this.translateX}px, ${this.translateY}px) scale(${this.scale})`;
    }

    reset() {
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.updateImageTransform();
        this.resetZoomButton.style.display = 'none';
        this.photoContainer.classList.remove('zoomed');
    }

    initEventListeners() {
        // Zoom mit Mausrad
        this.photoContainer.addEventListener('wheel', (e) => {
            e.preventDefault();

            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            const newScale = this.scale * delta;
            const isZoomingIn = delta > 1;

            // Limitiere Zoom zwischen 1x und 5x
            if (newScale >= 1 && newScale <= 5) {
                if (newScale <= 1) {
                    // Bei Zoom 1x: Zurücksetzen auf Zentrum
                    this.reset();
                } else {
                    if (isZoomingIn) {
                        // Zoom IN: Zoom zum Mauscursor
                        const rect = this.photoImage.getBoundingClientRect();
                        const containerRect = this.photoContainer.getBoundingClientRect();

                        // Relative Position im Container (0 bis 1)
                        const mouseX = (e.clientX - containerRect.left) / containerRect.width;
                        const mouseY = (e.clientY - containerRect.top) / containerRect.height;

                        // Aktuelle Bildposition relativ zum Mauszeiger
                        const oldWidth = rect.width / this.scale;
                        const oldHeight = rect.height / this.scale;

                        this.scale = newScale;

                        const newWidth = oldWidth * this.scale;
                        const newHeight = oldHeight * this.scale;

                        // Berechne neue Translation basierend auf Mausposition
                        this.translateX = this.translateX - (newWidth - rect.width) * (mouseX - 0.5);
                        this.translateY = this.translateY - (newHeight - rect.height) * (mouseY - 0.5);
                    } else {
                        // Zoom OUT: Bewege schrittweise zum Zentrum (0, 0)
                        const oldScale = this.scale;
                        this.scale = newScale;

                        // Je näher an 1x, desto mehr nähern wir uns (0, 0)
                        // Bei scale=1 soll translateX/Y = 0 sein
                        const centeringFactor = (this.scale - 1) / (oldScale - 1);
                        this.translateX *= centeringFactor;
                        this.translateY *= centeringFactor;
                    }

                    this.resetZoomButton.style.display = 'inline-block';
                    this.photoContainer.classList.add('zoomed');
                }

                this.updateImageTransform();
            }
        });

        // Pan mit Maus - funktioniert sofort beim ersten Klick
        this.photoContainer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            this.isPanning = true;
            this.startX = e.clientX - this.translateX;
            this.startY = e.clientY - this.translateY;
            this.photoContainer.style.cursor = 'grabbing';
        });

        document.addEventListener('mousemove', (e) => {
            if (this.isPanning && this.scale > 1) {
                this.translateX = e.clientX - this.startX;
                this.translateY = e.clientY - this.startY;
                this.updateImageTransform();
            }
        });

        document.addEventListener('mouseup', () => {
            if (this.isPanning) {
                this.isPanning = false;
                this.photoContainer.style.cursor = this.scale > 1 ? 'move' : 'grab';
            }
        });

        // Touch-Support für Mobile
        this.photoContainer.addEventListener('touchstart', (e) => {
            if (e.touches.length === 2) {
                e.preventDefault();
                this.initialDistance = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
            } else if (e.touches.length === 1 && this.scale > 1) {
                this.touchStartX = e.touches[0].clientX - this.translateX;
                this.touchStartY = e.touches[0].clientY - this.translateY;
            }
        });

        this.photoContainer.addEventListener('touchmove', (e) => {
            if (e.touches.length === 2) {
                e.preventDefault();
                const currentDistance = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );

                const delta = currentDistance / this.initialDistance;
                const newScale = this.scale * delta;

                if (newScale >= 1 && newScale <= 5) {
                    this.scale = newScale;
                    this.updateImageTransform();

                    if (this.scale > 1) {
                        this.resetZoomButton.style.display = 'inline-block';
                        this.photoContainer.classList.add('zoomed');
                    }
                }

                this.initialDistance = currentDistance;
            } else if (e.touches.length === 1 && this.scale > 1) {
                e.preventDefault();
                this.translateX = e.touches[0].clientX - this.touchStartX;
                this.translateY = e.touches[0].clientY - this.touchStartY;
                this.updateImageTransform();
            }
        });

        // Zoom zurücksetzen Button
        this.resetZoomButton.addEventListener('click', () => {
            this.reset();
        });
    }
}
