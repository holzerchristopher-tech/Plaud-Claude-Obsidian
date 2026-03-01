// This file exports functions that interact with the Plaud API, similar to the Claude API, for additional functionality. 

export const fetchPlaudData = async (endpoint: string, options: RequestInit = {}): Promise<any> => {
    const response = await fetch(`https://api.plaud.com/${endpoint}`, options);
    if (!response.ok) {
        throw new Error(`Error fetching data from Plaud API: ${response.statusText}`);
    }
    return response.json();
};

export const sendPlaudRequest = async (endpoint: string, data: any): Promise<any> => {
    const response = await fetch(`https://api.plaud.com/${endpoint}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    });
    if (!response.ok) {
        throw new Error(`Error sending request to Plaud API: ${response.statusText}`);
    }
    return response.json();
};