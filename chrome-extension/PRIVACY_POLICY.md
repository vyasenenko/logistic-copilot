# Privacy Policy for Logistic Copilot Chrome Extension

**Effective date:** April 30, 2026  
**Last updated:** April 30, 2026

This Privacy Policy describes how the Logistic Copilot Chrome Extension ("Extension", "we", "our", or "us") collects, uses, stores, and shares information when you use the Extension.

## 1. Who We Are

Publisher: **[INSERT LEGAL ENTITY NAME]**  
Product: **Logistic Copilot Chrome Extension**  
Contact email for privacy requests: **[INSERT PRIVACY EMAIL]**

## 2. Scope

This Policy applies only to the Logistic Copilot Chrome Extension and related backend services used by the Extension (for example, `https://api.logisticopilot.com`).

## 3. Information We Collect

### 3.1 Information you provide directly

- Chat prompts and messages you type in the Extension.
- Optional voice input (audio) when you explicitly start voice dictation.
- Settings you configure in the Extension (such as backend URL and frontend URL).

### 3.2 Information from the current browser tab (feature-dependent)

When page context is enabled, the Extension can capture a limited snapshot of the active page, such as:

- Page URL, origin, and title.
- Selected text (if any).
- A shortened visible text excerpt from the page.
- Headings, meta description, and visible action labels.
- Capture timestamp and context availability status.

This data is captured to help the assistant respond to your request in the context of the page you are viewing.

### 3.3 Technical and usage information

- Conversation identifiers and timestamps.
- Message history needed to provide conversation continuity.
- Basic error details required to troubleshoot service issues.

## 4. How We Use Information

We use collected information to:

- Provide core Extension features (chat, context-aware responses, quote links, and conversation management).
- Process and stream assistant responses.
- Transcribe optional voice input to text (when used).
- Maintain conversation history and browser context per conversation.
- Improve reliability, security, and product quality.

We do **not** sell personal information.

## 5. Legal Basis (EEA/UK, where applicable)

Depending on your location, processing may rely on:

- Performance of a contract (providing the service you request),
- Legitimate interests (service security, debugging, and improvement),
- Consent (for optional features such as microphone-based voice input).

## 6. Data Sharing and Third Parties

To provide the service, data may be shared with infrastructure and AI subprocessors, including:

- AI/LLM providers used by backend runtime (for prompt processing).
- Audio transcription provider (for optional voice dictation).
- Cloud hosting, networking, and database providers.

Data is shared only as needed to provide functionality. We do not share data for unrelated advertising purposes.

## 7. Data Storage and Retention

- Extension local data is stored using Chrome extension local storage.
- Conversation messages and associated context can be stored on backend systems (for example, PostgreSQL) to support conversation history.
- When you delete a conversation in the Extension, associated conversation messages are removed from backend conversation storage.

Retention periods may vary by operational requirements, legal obligations, and security needs. We keep data only as long as necessary for the purposes described in this Policy.

## 8. Permissions and Why They Are Needed

The Extension requests Chrome permissions to provide features:

- `storage`: Save local settings and UI state.
- `tabs` / `activeTab`: Identify and interact with the active tab.
- `scripting`: Capture current page context when required.
- `sidePanel`: Display the Extension side panel UI.
- Host permissions (including `https://api.logisticopilot.com/*` and development localhost URLs): Communicate with backend APIs and support configured environments.

## 9. Your Choices and Controls

You can:

- Choose whether to use page context in chat.
- Delete conversations from the Extension UI.
- Stop using optional voice input features.
- Remove the Extension at any time to stop further local collection.

To request access, correction, or deletion, contact us at **[INSERT PRIVACY EMAIL]**.

## 10. International Transfers

If data is processed outside your country of residence, we apply reasonable safeguards consistent with applicable law.

## 11. Security

We use reasonable technical and organizational safeguards to protect data. However, no method of transmission or storage is fully secure, and absolute security cannot be guaranteed.

## 12. Children's Privacy

The Extension is not directed to children under 13 (or higher age threshold where required by local law), and we do not knowingly collect personal information from children.

## 13. Changes to This Policy

We may update this Policy from time to time. We will post the updated version with a revised "Last updated" date.

## 14. Contact

For privacy questions or requests, contact: **[INSERT PRIVACY EMAIL]**  
Controller/Publisher: **[INSERT LEGAL ENTITY NAME]**

---

## Chrome Web Store Disclosure Notes (for publisher use)

Before submission, make sure your Chrome Web Store Data Safety disclosures match actual behavior, including:

- Collection of website content (when page context is enabled).
- Processing of user-provided chat content.
- Optional audio processing for transcription.
- Storage of conversation history and related metadata.

Replace all placeholders in this policy before publishing.
