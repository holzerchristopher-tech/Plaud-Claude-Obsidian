export interface PluginSettings {
    theme: string;
    language: string;
    notificationsEnabled: boolean;
}

export interface UserPreferences {
    fontSize: number;
    showLineNumbers: boolean;
}

export interface ApiResponse<T> {
    success: boolean;
    data: T;
    error?: string;
}

export interface ModalOptions {
    title: string;
    message: string;
    confirmButtonText?: string;
    cancelButtonText?: string;
}

export interface RibbonOptions {
    label: string;
    icon?: string;
    onClick: () => void;
}