import resend

from app.config import RESEND_API_KEY

resend.api_key = RESEND_API_KEY


def send_welcome_email(user_email: str, username: str):
    try:
        params: resend.Emails.SendParams = {
            "from": "Wolfy <hello@wolfy.online>",
            "to": [user_email],
            "subject": "Welcome to Wolfy",
            "html": f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Welcome to Wolfy</title>
</head>

<body style="margin:0; padding:0; background:#f5f5f5; font-family:Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:40px 20px;">

        <table
          width="600"
          cellpadding="0"
          cellspacing="0"
          style="
            background:#ffffff;
            border-radius:12px;
            overflow:hidden;
          "
        >

          <tr>
            <td
              align="center"
              style="
                background:#000000;
                padding:40px 20px;
              "
            >

              <h1
                style="
                  color:#ffffff;
                  margin:0;
                  letter-spacing:1px;
                "
              >
                WOLFY
              </h1>

              <p style="color:#bbbbbb;">
                Secure • Modern • Authentic
              </p>

            </td>
          </tr>

          <tr>
            <td
              style="
                padding:50px 40px;
                color:#333333;
                line-height:1.7;
              "
            >

              <h2 style="margin-top:0;">
                Welcome to Wolfy
              </h2>

              <p>
                Dear {username},
              </p>

              <p>
                We are delighted to welcome you to Wolfy and sincerely
                appreciate your decision to become a part of our platform.
              </p>

              <p>
                Your account has been successfully created and you are now
                ready to explore everything Wolfy has to offer.
              </p>

              <div
                style="
                  text-align:center;
                  margin:40px 0;
                "
              >

                <a
                  href="https://wolfy.online"
                  style="
                    display:inline-block;
                    background:#000000;
                    color:#ffffff;
                    padding:16px 32px;
                    text-decoration:none;
                    border-radius:8px;
                    font-weight:bold;
                    font-size:16px;
                  "
                >
                  Explore Wolfy
                </a>

              </div>

              <p>
                Thank you for joining Wolfy.
              </p>

              <p>
                Warm regards,<br>
                <strong>The Wolfy Team</strong>
              </p>

            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>
            """,
        }

        email = resend.Emails.send(params)
        print("Welcome email sent successfully")
        print(email)
        return True

    except Exception as e:
        print("Failed to send welcome email")
        print(e)
        return False
