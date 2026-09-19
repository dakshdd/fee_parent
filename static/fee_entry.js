const months = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March"
];

// --- Autocomplete search ---
document.getElementById("searchBox").addEventListener("keyup", function () {
    let q = this.value;
    if (q.length < 1) {
        document.getElementById("studentList").innerHTML = "";
        document.getElementById("details").innerHTML = "";
        return;
    }
    fetch("/fee/autocomplete?q=" + encodeURIComponent(q))
        .then(res => res.json())
        .then(data => {
            let list = document.getElementById("studentList");
            list.innerHTML = "";
            data.forEach(r => {
                let option = document.createElement("option");
                option.value = r.adm_code;
                option.textContent =
                    `${r.adm_code} | ${r.student_name} | ${r.class || "-"} | ${r.father_name || "-"}`;
                list.appendChild(option);
            });
            if (data.length === 1) {
                loadDetails(data[0].adm_code);
            }
        });
});

// --- Load student details ---
function loadDetails(adm_code) {
    fetch("/fee/details?adm_code=" + encodeURIComponent(adm_code))
        .then(res => res.json())
        .then(r => {
            if (!r.adm_code) {
                document.getElementById("details").innerHTML = "<p>No details found.</p>";
                return;
            }

            let html = "<h3>Student Details</h3>";
            html += `<p><b>Admission Code:</b> ${r.adm_code}</p>`;
            html += `<p><b>Name:</b> ${r.student_name}</p>`;
            html += `<p><b>Class:</b> ${r.class}</p>`;
            html += `<p><b>Father:</b> ${r.father_name}</p>`;

            // Payment form
            html += `
  <form method="post" action="/fee/receive">
    <input type="hidden" name="adm_code" value="${r.adm_code}">
    <label>Month</label>
    <select name="month" id="monthSelect"></select>
    <label>Payment Mode</label>
    <select name="mode" required>
      <option value="Cash">Cash</option>
      <option value="Cheque">Cheque</option>
      <option value="UPI">UPI</option>
    </select>
    <label>Remark</label>
    <input type="text" name="remark" id="remarkBox" placeholder="Enter remark">
    <label>Amount</label>
    <input type="number" step="0.01" name="amount" id="amountBox" required>
    <button type="submit">Receive</button>
  </form>
`;

            document.getElementById("details").innerHTML = html;

            let monthSelect = document.getElementById("monthSelect");

            // Populate month dropdown
            months.forEach(m => {
                let opt = document.createElement("option");
                opt.value = m;
                opt.textContent = m;
                monthSelect.appendChild(opt);
            });

            // ✅ Call backend to get next unpaid month
            fetch("/fee/next_month?adm_code=" + encodeURIComponent(adm_code))
                .then(res => res.json())
                .then(data => {
                    if (data.next_month) {
                        monthSelect.value = data.next_month;

                        // Update amount for that month
                        fetch("/fee/month_total?adm_code=" + encodeURIComponent(adm_code) + "&month=" + data.next_month)
                            .then(res => res.json())
                            .then(calc => {
                                document.getElementById("amountBox").value = parseFloat(calc.total).toFixed(2);
                            });
                    }

                    // Disable already paid months
                    if (data.paid_months) {
                        data.paid_months.forEach(pm => {
                            let opt = [...monthSelect.options].find(o => o.value === pm);
                            if (opt) {
                                opt.disabled = true;
                                opt.textContent = opt.value + " (Paid)";
                            }
                        });
                    }
                });

            // 🔄 Auto-update amount when month changes
            monthSelect.addEventListener("change", function () {
                fetch("/fee/month_total?adm_code=" + encodeURIComponent(adm_code) + "&month=" + this.value)
                    .then(res => res.json())
                    .then(calc => {
                        document.getElementById("amountBox").value = parseFloat(calc.total).toFixed(2);
                    });
            });
        });
}

// --- On student selection ---
document.getElementById("studentList").addEventListener("change", function () {
    loadDetails(this.value);
});
