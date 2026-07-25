document.addEventListener('DOMContentLoaded', () => {
    const followBtn = document.getElementById('follow-btn');
    const followerCount = document.getElementById('follower-count');

    if (followBtn) {
        followBtn.addEventListener('click', async () => {
            const username = followBtn.getAttribute('data-username');
            try {
                const response = await fetch(`/api/follow/${username}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                const data = await response.json();

                if (response.ok) {
                    if (data.action === 'followed') {
                        followBtn.classList.add('following');
                        followBtn.textContent = 'Siguiendo';
                    } else {
                        followBtn.classList.remove('following');
                        followBtn.textContent = 'Seguir';
                    }
                    followerCount.textContent = data.follower_count;
                } else {
                    alert(data.error || 'Error al procesar la solicitud');
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Error de conexión');
            }
        });
    }
});
