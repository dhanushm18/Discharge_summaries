#!/usr/bin/env python
import sys
import os
import warnings
from datetime import datetime

# Filter out external library syntax warnings
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Add the src folder to sys.path so we can import modules correctly
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from discharge_summaries.coordinator import ClinicalCoordinator
from discharge_summaries.feedback.learning_loop import simulate_feedback_training

def run():
    """Run the complete clinically-safe agentic discharge summary system and learning loop."""
    print("==================================================================")
    print("CLINICALLY SAFE DISCHARGE SUMMARY AGENT SYSTEM (CrewAI Take-Home)")
    print("==================================================================")
    
    # 1. Part 1 - Run the Clinical Safe Agentic coordinator loop
    try:
        coordinator = ClinicalCoordinator()
        coordinator.run_agentic_loop()
        print("\n[PART 1 SUCCESS] Agentic coordinator loop completed successfully.")
        print(f"  - Step Traces logged to: {coordinator.trace_path}")
        print(f"  - Structured JSON draft saved to: {coordinator.output_json_path}")
        print(f"  - Human-readable Markdown summary saved to: {coordinator.output_md_path}")
    except Exception as e:
        print(f"\n[PART 1 FAILED] An error occurred during agentic loop: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    print("\n" + "="*66 + "\n")
    
    # 2. Part 2 - Run the simulated clinician feedback learning loop
    try:
        simulate_feedback_training()
        print("\n[PART 2 SUCCESS] Simulated reviewer and learning feedback loop executed.")
        print("  - Clinical correction guidelines extracted to scratch memory.")
        print("  - Match/Reward metrics and learning curve saved to outputs/learning_curve.json")
    except Exception as e:
        print(f"\n[PART 2 FAILED] An error occurred during reinforcement training: {e}")
        sys.exit(1)

    print("\n==================================================================")
    print("EXECUTION COMPLETED SUCCESSFULLY. ALL OUTPUTS GENERATED.")
    print("==================================================================")

def train():
    """Train the crew (Placeholder for CLI backward-compatibility)."""
    print("Training command is deprecated. Please use main execution run command.")

def replay():
    """Replay the crew execution (Placeholder)."""
    print("Replay command is deprecated. Please use main execution run command.")

def test():
    """Test the crew execution."""
    run()

if __name__ == "__main__":
    run()
