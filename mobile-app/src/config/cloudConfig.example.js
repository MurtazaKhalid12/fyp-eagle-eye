// ============================================================
//  EagleEye — cloud config TEMPLATE
// ============================================================
//  Copy this file to  cloudConfig.js  and fill in your own values.
//  cloudConfig.js is gitignored so real credentials are never committed.
// ============================================================

export const CLOUD = {
  deviceId: 'cam-01',                              // match firmware DEV_DEVICE_ID

  mqtt: {
    url: 'wss://YOUR_CLUSTER.s1.eu.hivemq.cloud:8884/mqtt',
    username: 'app-user',                          // a HiveMQ credential
    password: 'YOUR_APP_PASSWORD',
  },

  relayBase: 'wss://YOUR_RELAY.deno.net',          // Deno/Node relay host (wss, no trailing /)
};

export const topics = {
  status: (id) => `eagleeye/${id}/status`,
  alert:  (id) => `eagleeye/${id}/alert`,
  cmd:    (id) => `eagleeye/${id}/cmd`,
  stream: (id) => `eagleeye/${id}/stream`,
};
