/* WPGuard — Cloud access lead capture (pricing page)
   Same-origin script (script-src 'self'); no inline handlers, no external deps.
   Posts to the shared kaibuilds capture service. See site/pricing/index.html.
*/
(function () {
  "use strict";

  var ENDPOINT = "https://kaibuilds.com/api/lead";
  var SLUG = "wpmcpserver";

  function gtagSafe() {
    if (typeof window.gtag === "function") {
      window.gtag.apply(window, arguments);
    }
  }

  // Tier-specific "Request this plan" / "Talk to us" links on each pricing
  // card: track intent, pre-select the plan in the form, scroll there.
  var planLinks = document.querySelectorAll(".request-plan-link[data-plan-tier]");
  planLinks.forEach(function (link) {
    link.addEventListener("click", function () {
      var tier = link.getAttribute("data-plan-tier") || "";
      gtagSafe("event", "select_plan", { plan_tier: tier });

      var select = document.getElementById("lead-plan");
      if (select && tier) {
        select.value = tier;
      }

      if (link.getAttribute("data-note") === "founding") {
        var message = document.getElementById("lead-message");
        if (message && !message.value) {
          message.value = "Founding Agency offer (first 20 agencies, $39/month for 12 months).";
        }
      }
    });
  });

  var form = document.getElementById("lead-capture-form");
  if (!form) {
    return;
  }

  var statusEl = document.getElementById("lead-form-status");
  var submitBtn = document.getElementById("lead-submit-btn");

  function setStatus(message, kind) {
    if (!statusEl) {
      return;
    }
    statusEl.textContent = message;
    statusEl.className = "form-status" + (kind ? " " + kind : "");
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();

    var name = document.getElementById("lead-name").value.trim();
    var email = document.getElementById("lead-email").value.trim();
    var company = document.getElementById("lead-company").value.trim();
    var planTier = document.getElementById("lead-plan").value;
    var message = document.getElementById("lead-message").value.trim();

    if (!name || !email) {
      setStatus("Name and email are required.", "error");
      return;
    }

    var utmSource = "";
    try {
      utmSource = new URLSearchParams(window.location.search).get("utm_source") || "";
    } catch (err) {
      utmSource = "";
    }

    var payload = {
      slug: SLUG,
      name: name,
      email: email,
      company: company,
      plan_tier: planTier,
      message: message,
      page: window.location.pathname,
      // wpmcpserver.com has no RESEND_FROM_EMAIL_MAP_JSON entry on the shared
      // capture service, so its auto-reply would otherwise send under the
      // default KaiCalls-branded sender. call_consent stays false here so
      // this never gets treated as a call-back opt-in.
      call_consent: false,
      utm_source: utmSource
    };

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Sending…";
    }
    setStatus("", "");

    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Request failed: " + response.status);
        }
        return response.json();
      })
      .then(function () {
        gtagSafe("event", "lead_submit_success", { plan_tier: planTier });
        setStatus("Thanks — we received your request and will follow up by email.", "success");
        form.reset();
      })
      .catch(function () {
        setStatus("Something went wrong sending that. Please email hello@wpmcpserver.com directly.", "error");
      })
      .then(function () {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Request Cloud access";
        }
      });
  });
})();
