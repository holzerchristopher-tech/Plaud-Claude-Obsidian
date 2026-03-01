// This file exports functions to create and manage ribbon elements in the user interface, allowing users to interact with the plugin easily.

export function createRibbonElement(label: string, onClick: () => void): HTMLElement {
    const ribbonElement = document.createElement('div');
    ribbonElement.className = 'ribbon-element';
    ribbonElement.innerText = label;
    ribbonElement.onclick = onClick;
    return ribbonElement;
}

export function addRibbonToContainer(container: HTMLElement, ribbonElement: HTMLElement): void {
    container.appendChild(ribbonElement);
}

export function removeRibbonFromContainer(container: HTMLElement, ribbonElement: HTMLElement): void {
    container.removeChild(ribbonElement);
}