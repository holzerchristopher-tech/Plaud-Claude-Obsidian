import axios from 'axios';

const CLAUDE_API_URL = 'https://api.claude.ai/v1';

export async function sendRequestToClaude(prompt: string): Promise<any> {
    try {
        const response = await axios.post(`${CLAUDE_API_URL}/generate`, {
            prompt: prompt,
        });
        return response.data;
    } catch (error) {
        console.error('Error sending request to Claude API:', error);
        throw error;
    }
}

export async function getClaudeResponse(prompt: string): Promise<string> {
    const data = await sendRequestToClaude(prompt);
    return data.response; // Adjust based on actual API response structure
}