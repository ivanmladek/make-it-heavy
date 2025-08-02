import os
import json
import subprocess
import sys
from typing import List, Dict, Any, Optional

def run_single_experiment(seed: int, run_id: int) -> Optional[float]:
    """
    Run a single experiment with the given seed and return the score.
    """
    env = os.environ.copy()
    env["EMERGENT_GAME_SEED"] = str(seed)
    
    try:
        # Run the multi_agent_runner.py script
        result = subprocess.run(
            [sys.executable, "-u", "multi_agent_runner.py"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        # Parse the output to extract the score
        output = result.stdout
        lines = output.split('\n')
        
        # Look for the score line
        for line in lines:
            if line.startswith("Score: "):
                # Extract the score value
                score_str = line.split("Score: ")[1].split("%")[0]
                return float(score_str)
        
        # If no score found, check if there was a valid proposal
        if "No valid proposal received." in output:
            return 0.0
            
        return None  # Unknown result
        
    except subprocess.TimeoutExpired:
        print(f"Run {run_id} with seed {seed} timed out")
        return None
    except Exception as e:
        print(f"Run {run_id} with seed {seed} failed with error: {e}")
        return None

def run_multiple_experiments(seed: int, num_runs: int = 3) -> Dict[str, Any]:
    """
    Run multiple experiments with the same seed and return statistics.
    """
    print(f"Running {num_runs} experiments with seed {seed}")
    
    scores = []
    valid_runs = 0
    
    for i in range(num_runs):
        print(f"Running experiment {i+1}/{num_runs}")
        score = run_single_experiment(seed, i+1)
        
        if score is not None:
            scores.append(score)
            valid_runs += 1
            print(f"  Score: {score}%")
        else:
            print(f"  Failed to get score")
    
    if not scores:
        return {
            "seed": seed,
            "num_runs": num_runs,
            "valid_runs": 0,
            "average_score": 0.0,
            "max_score": 0.0,
            "min_score": 0.0,
            "scores": []
        }
    
    return {
        "seed": seed,
        "num_runs": num_runs,
        "valid_runs": valid_runs,
        "average_score": sum(scores) / len(scores),
        "max_score": max(scores),
        "min_score": min(scores),
        "scores": scores
    }

def main():
    # Default seed is 42
    seed = int(os.getenv("EMERGENT_GAME_SEED", "42"))
    num_runs = int(os.getenv("NUM_RUNS", "3"))
    
    # Run multiple experiments
    results = run_multiple_experiments(seed, num_runs)
    
    # Print results
    print("\n=== Experiment Results ===")
    print(f"Seed: {results['seed']}")
    print(f"Number of runs: {results['num_runs']}")
    print(f"Valid runs: {results['valid_runs']}")
    print(f"Average score: {results['average_score']:.1f}%")
    print(f"Maximum score: {results['max_score']:.1f}%")
    print(f"Minimum score: {results['min_score']:.1f}%")
    print(f"All scores: {results['scores']}")
    
    # Save results to file
    with open(f"experiment_results_seed_{seed}.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to experiment_results_seed_{seed}.json")

if __name__ == "__main__":
    main()