"""
Email notification service.

Currently a structured stub — logs the email instead of sending it.
To wire up real SMTP, replace `_send_via_smtp` with an aiosmtplib call
or swap to AWS SES / SendGrid by changing only this file.

Usage (in an endpoint):
    background_tasks.add_task(
        notify_user_invited,
        invitee_login="bob",
        project_name="My Project",
        inviter_login="alice",
    )
"""

import logging

logger = logging.getLogger(__name__)


async def _send_via_smtp(
    to_address: str,
    subject: str,
    body: str,
) -> None:
    """
    Stub — replace with real transport when SMTP creds are available.

    Example real implementation with aiosmtplib:
        async with aiosmtplib.SMTP(hostname=settings.smtp_host, port=587) as smtp:
            await smtp.login(settings.smtp_user, settings.smtp_password)
            msg = EmailMessage()
            msg["From"] = settings.smtp_from
            msg["To"] = to_address
            msg["Subject"] = subject
            msg.set_content(body)
            await smtp.send_message(msg)
    """
    logger.info(
        "Email notification dispatched",
        extra={
            "email_to": to_address,
            "subject": subject,
            "body_preview": body[:120],
        },
    )


async def notify_user_invited(
    invitee_login: str,
    project_name: str,
    inviter_login: str,
) -> None:
    """Notify a user they have been invited to a project."""
    subject = f"You've been invited to project '{project_name}'"
    body = (
        f"Hi {invitee_login},\n\n"
        f"{inviter_login} has invited you to collaborate on '{project_name}'.\n"
        f"Log in to access the project.\n\n"
        f"— Project Management Dashboard"
    )
    # In production, to_address would be looked up from the user's email field.
    # For now we use login as a placeholder.
    to_address = f"{invitee_login}@example.com"
    await _send_via_smtp(to_address, subject, body)
    logger.info(
        "Invite notification sent",
        extra={"invitee": invitee_login, "project": project_name},
    )


async def notify_share_link(email: str, project_name: str, join_url: str) -> None:
    """Send a project join link to an (unregistered) email address."""
    subject = f"You've been invited to join '{project_name}'"
    body = (
        f"Hi,\n\n"
        f"You've been invited to collaborate on '{project_name}'.\n"
        f"Open this link to join: {join_url}\n\n"
        f"— Project Management Dashboard"
    )
    await _send_via_smtp(email, subject, body)
    logger.info("Share link sent", extra={"email": email, "project": project_name})


async def notify_project_deleted(
    owner_login: str,
    project_name: str,
    member_logins: list[str],
) -> None:
    """Notify all members that a project was deleted."""
    for login in member_logins:
        subject = f"Project '{project_name}' has been deleted"
        body = (
            f"Hi {login},\n\n"
            f"The project '{project_name}' owned by {owner_login} has been deleted.\n"
            f"All associated documents have been removed.\n\n"
            f"— Project Management Dashboard"
        )
        await _send_via_smtp(f"{login}@example.com", subject, body)
