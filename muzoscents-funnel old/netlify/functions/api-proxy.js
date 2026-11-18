// netlify/functions/api-proxy.js
const fetch = require('node-fetch');

exports.handler = async (event) => {
    const API_BASE = process.env.API_BASE;

    if (!API_BASE) {
        return {
            statusCode: 500,
            body: JSON.stringify({ error: 'API_BASE is not configured' }),
            headers: { 'Content-Type': 'application/json' },
        };
    }

    // Strip the function prefix to get the original path
    let path = event.path || '';
    path = path.replace(/^\/\.netlify\/functions\/api-proxy/, '');

    const query = event.rawQuery ? '?' + event.rawQuery : '';
    const targetUrl = `${API_BASE}${path}${query}`;

    const headers = { ...event.headers };
    delete headers.host;
    delete headers['content-length'];

    try {
        const response = await fetch(targetUrl, {
            method: event.httpMethod,
            headers,
            body: event.httpMethod === 'GET' || event.httpMethod === 'HEAD'
                ? undefined
                : event.body,
            redirect: 'manual',
        });

        const responseBody = await response.text();

        return {
            statusCode: response.status,
            headers: {
                ...Object.fromEntries(response.headers.entries()),
                'access-control-allow-origin': '*',
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
