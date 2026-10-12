# Frontend Assets

The staff and student Vite applications are built during the WEAVE application image build.

Their production output is copied into the final `weave-cbt:<version>` image as static files. No Vite development server or separate frontend container is used in production.

The API container serves these static files after the backend is ready, which naturally keeps the UI unavailable until the API process is running.
