

		
		w3.includeHTML();

        // Change style of navbar on scroll
        window.onscroll = function () { myFunction() };
        function myFunction() {
            var navbar = document.getElementById("myNavbar");
            if (document.body.scrollTop > 100 || document.documentElement.scrollTop > 100) {
                navbar.className = "w3-bar" + " w3-card" + " w3-animate-top" + " w3-white";
            } else {
                navbar.className = navbar.className.replace(" w3-card w3-animate-top w3-white", "");
            }
        }

        // Used to toggle the menu on small screens when clicking on the menu button
        function toggleFunction() {
            var x = document.getElementById("navDemo");
            if (x.className.indexOf("w3-show") == -1) {
                x.className += " w3-show";
            } else {
                x.className = x.className.replace(" w3-show", "");
            }
        }
        
        
        const observerOptions = {
		  root: null,
		  rootMargin: "0px",
		  threshold: 0.1
		};

		function observerCallback(entries, observer) {
		  entries.forEach(entry => {
			if (entry.isIntersecting) {
			  // fade in observed elements that are in view
			  entry.target.classList.replace('fadeOut', 'fadeIn');
			} else {
			  // fade out observed elements that are not in view
			  entry.target.classList.replace('fadeIn', 'fadeOut');
			}
		  });
		}

		const observer = new IntersectionObserver(observerCallback, observerOptions);

		const fadeElms = document.querySelectorAll('.fade');
		fadeElms.forEach(el => observer.observe(el));
		
		




