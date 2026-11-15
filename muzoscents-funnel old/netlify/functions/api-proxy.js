// netlify/functions/api-proxy.js
// Forwards requests to the backend URL stored in the API_BASE env var.
// The HF URL never reaches the browser.

exports.handler = async (event) => {
    const API_BASE = process.env.API_BASE;

    if (!API_BASE) {
        return {
            statusCode: 500,
            body: JSON.stringify({ error: 'API_BASE is not configured' }),
            headers: { 'Content-Type': 'application/json' },
        };
    }

    // The rewrite in netlify.toml maps /api/* → this function.
    // We reconstruct the original path by stripping the function prefix
    // if Netlify gave us the raw path, and keeping the query string intact.
    let path = event.path || '';
    path = path.replace(/^\/\.netlify\/functions\/api-proxy/, '');
    path = path.replace(/^\/api/, '');          // in case the rewrite didn't strip it

    const query = event.rawQuery ? '?' + event.rawQuery : '';
    const targetUrl = `${API_BASE}${path}${query}`;

    // Forward the request, preserving method, headers and body.
    const headers = { ...event.headers };
    delete headers.host;                        // let fetch set the correct Host
    delete headers['content-length'];           // fetch recalculates this

    try {
        const response = await fetch(targetUrl, {
            method: event.httpMethod,
            headers,
            body: event.httpMethod === 'GET' || event.httpMethod === 'HEAD'
                ? undefined
                : event.body,
        });

        const responseBody = await response.text();

        return {
            statusCode: response.status,
            headers: {
                ...Object.fromEntries(response.headers.entries()),
                'access-control-allow-origin': '*',   // optional: keeps CORS simple while testing
            },
            body: responseBody,
        };
    } catch (err) {
        return {
            statusCode: 502,
            body: JSON.stringify({ error: 'Proxy request failed', detail: err.message }),
            headers: { 'Content-Type': 'application/json' },
        };
    }
};
