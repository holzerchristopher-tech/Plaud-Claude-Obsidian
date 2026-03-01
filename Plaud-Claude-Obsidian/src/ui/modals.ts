// This file exports functions to create and manage modal dialogs within the plugin's user interface.

export function createModal(title: string, content: string): HTMLElement {
    const modal = document.createElement('div');
    modal.classList.add('modal');

    const modalTitle = document.createElement('h2');
    modalTitle.textContent = title;
    modal.appendChild(modalTitle);

    const modalContent = document.createElement('div');
    modalContent.innerHTML = content;
    modal.appendChild(modalContent);

    const closeButton = document.createElement('button');
    closeButton.textContent = 'Close';
    closeButton.onclick = () => {
        modal.remove();
    };
    modal.appendChild(closeButton);

    document.body.appendChild(modal);
    return modal;
}

export function showModal(title: string, content: string): void {
    createModal(title, content);
}