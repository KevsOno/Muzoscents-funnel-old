import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.logiflow.app',
  appName: 'LogiFlow',
  webDir: 'dist',
  bundledWebRuntime: false,
  android: {
    allowMixedContent: true,
  },
  plugins: {
    // The community background-geolocation plugin owns the foreground
    // service — it declares its own Android permissions via the plugin
    // manifest so no extra entry is required here.
  },
};

export default config;
