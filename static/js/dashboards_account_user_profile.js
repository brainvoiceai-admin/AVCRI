function previewProfilePicture(input) {
			if (input.files && input.files[0]) {
				// Validate file size (5MB)
				if (input.files[0].size > 5 * 1024 * 1024) {
					alert('File size should be less than 5MB.');
					input.value = '';
					return;
				}
				
				// Validate file type
				const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif'];
				if (!allowedTypes.includes(input.files[0].type)) {
					alert('Invalid file type. Please upload a JPEG, PNG, or GIF image.');
					input.value = '';
					return;
				}
				
				const reader = new FileReader();
				reader.onload = function(e) {
					document.getElementById('profile-preview').src = e.target.result;
				};
				reader.readAsDataURL(input.files[0]);
			}
		}