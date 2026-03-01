// src/main.ts

import { App } from 'obsidian';
import Settings from './settings';
import { initializeModals } from './ui/modals';
import { initializeRibbons } from './ui/ribbons';
import { setupClaudeAPI } from './api/claude';
import { setupPlaudAPI } from './api/plaud';
import { loadSettings } from './utils/helpers';

export default class PlaudClaudePlugin {
    private app: App;
    private settings: Settings;

    constructor(app: App) {
        this.app = app;
        this.settings = new Settings();
    }

    async onload() {
        await this.loadSettings();
        this.initializeUI();
        this.setupAPIs();
        this.addEventListeners();
    }

    async loadSettings() {
        this.settings = await loadSettings(this.app);
    }

    initializeUI() {
        initializeModals(this.app);
        initializeRibbons(this.app);
    }

    setupAPIs() {
        setupClaudeAPI(this.settings);
        setupPlaudAPI(this.settings);
    }

    addEventListeners() {
        // Add event listeners for plugin lifecycle events
    }

    onunload() {
        // Cleanup code when the plugin is unloaded
    }
}