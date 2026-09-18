// 1. Move this OUTSIDE of the DOMContentLoaded block so it's globally accessible
function switchView(viewId) {
    document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
    document.getElementById(viewId).classList.add('active');
}

// 2. Keep the hotspot logic inside the DOMContentLoaded block
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('anatomy-wrapper').addEventListener('click', (e) => {
        if (e.target.classList.contains('hotspot')) {
            const hotspot = e.target;
            const currentSection = hotspot.closest('.view-section');
            
            // Hide only overlays within this section
            currentSection.querySelectorAll('.layer-image.overlay').forEach(img => {
                img.classList.remove('active');
            });

            // Show target
            const targetId = hotspot.getAttribute('data-target');
            const targetImg = currentSection.querySelector('#' + targetId);
            
            if (targetImg) {
                targetImg.classList.add('active');
            }
        }
    });
});