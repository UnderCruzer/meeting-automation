/**
 * Resolve attendee emails to Slack user IDs via users.lookupByEmail API
 * Skips emails that are not found in the workspace (external attendees)
 * @param {Object} slackClient - Slack WebClient instance
 * @param {string[]} emails
 * @returns {string[]} Slack user IDs
 */
async function resolveSlackIds(slackClient, emails) {
  const results = await Promise.allSettled(
    emails.map((email) => slackClient.users.lookupByEmail({ email }))
  );

  return results
    .filter((r) => r.status === "fulfilled" && r.value.ok)
    .map((r) => r.value.user.id);
}

module.exports = { resolveSlackIds };
