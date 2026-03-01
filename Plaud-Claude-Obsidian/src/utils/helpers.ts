export function formatData(data: any): string {
    // Implement data formatting logic here
    return JSON.stringify(data, null, 2);
}

export function manageState<T>(initialState: T): [T, (newState: T) => void] {
    let state = initialState;

    const setState = (newState: T) => {
        state = newState;
    };

    return [state, setState];
}

export function isValidEmail(email: string): boolean {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return regex.test(email);
}

export function debounce(func: Function, delay: number) {
    let timeoutId: NodeJS.Timeout;
    return (...args: any[]) => {
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
        timeoutId = setTimeout(() => {
            func(...args);
        }, delay);
    };
}