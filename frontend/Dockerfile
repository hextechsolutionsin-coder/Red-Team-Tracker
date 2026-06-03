# =============================================================================
# Red Team Operations Tracker — Frontend Dockerfile
# Serves the vanilla HTML/CSS/JS single-page application via nginx.
# =============================================================================

FROM nginx:1.27-alpine

# Remove the default nginx configuration
RUN rm /etc/nginx/conf.d/default.conf

# Copy our custom nginx configuration
COPY nginx/nginx.conf /etc/nginx/conf.d/redboard.conf

# Copy the static frontend files
COPY frontend/ /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
