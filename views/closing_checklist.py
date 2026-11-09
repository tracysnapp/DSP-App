import streamlit as st


def render():
  st.title("Closing Checklist")

  # Inject custom CSS to clean up layout during printing
  st.markdown(
      """
        <style>
        @media print {
            .stButton, [data-testid="stSidebar"] {
                display: none !important;
            }
            header, footer {
                visibility: hidden;
            }
        }
        </style>
        """,
      unsafe_allow_html=True,
  )

  # Print Action Button
  if st.button("🖨️ Print Closing Checklist"):
    st.markdown(
        """
            <script>
                window.print();
            </script>
            """,
        unsafe_allow_html=True,
    )

  st.markdown("---")
  st.subheader("Shift Completion Tasks")

  # Checklist Items
  tasks = [
      "All delivery vans returned, parked, and secured.",
      "DVICs (Driver Vehicle Inspection Checklists) reviewed and closed.",
      "All rabbit devices (DAs) docked, accounted for, and charging.",
      "Keys collected, accounted for, and secured in the lockbox.",
      "Dispatch area, laptops, and station desk cleaned and locked.",
      "Incident logs and Cortex summaries updated for the evening shift.",
  ]

  completed_tasks = []
  for i, task in enumerate(tasks):
    completed_tasks.append(st.checkbox(task, key=f"closing_task_{i}"))

  if all(completed_tasks):
    st.success("All closing procedures completed and verified.")
