// Learn more https://docs.expo.dev/guides/customizing-metro
const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);

// ── Performance Optimizations ───────────────────────────────────────
// 1) Block large sibling directories from being watched by Metro.
//    Without this, Metro's file-watcher crawls the entire parent repo
//    (including ~31k dataset images), which makes every reload slow.
const parentDir = path.resolve(__dirname, '..');
config.watchFolders = [__dirname]; // Only watch the mobile-app folder

config.resolver = {
  ...config.resolver,
  // Explicitly block directories that should never be bundled
  blockList: [
    /.*[/\\]Downloaded_Dataset[/\\].*/,
    /.*[/\\]Human_Detection_Dataset[/\\].*/,
    /.*[/\\]Human_Detection_Dataset_Backup[/\\].*/,
    /.*[/\\]AI_Models[/\\].*/,
    /.*[/\\]CameraWebServer[/\\].*/,
    /.*[/\\]IOT_Project_FYP_integeration[/\\].*/,
    /.*[/\\]web-dashboard[/\\].*/,
    /.*[/\\]Human-vs-NonHuman[/\\].*/,
    /.*[/\\]\.git[/\\].*/,
  ],
};

// 2) Enable lazy bundling – only bundle modules when they are actually
//    needed, rather than everything up-front.
config.transformer = {
  ...config.transformer,
  minifierConfig: {
    ...config.transformer?.minifierConfig,
  },
};

module.exports = config;
